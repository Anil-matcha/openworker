use crate::http::{ApiError, App};
use axum::{
    body::Body,
    extract::{Path, Request},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
    Extension, Json,
};
use futures_util::TryStreamExt;
use openworker_artifacts::{Artifact, Error, Expected, Registration, Status};
use serde::Deserialize;
use serde_json::{json, Value};
use std::time::Duration;
fn public(a: &Artifact) -> Value {
    json!({"id":a.id,"session_id":a.registration.session_id,"turn_id":a.registration.turn_id,"name":a.registration.name,"content_type":a.registration.content_type,"size":a.registration.expected.size,"sha256":a.registration.expected.sha256,"status":a.status})
}
fn enabled(app: &App) -> Result<&openworker_artifacts::Store, ApiError> {
    app.artifacts
        .as_ref()
        .ok_or_else(|| ApiError(Error::Unconfigured.into()))
}
fn transfer(app: &App) -> Result<tokio::sync::OwnedSemaphorePermit, ApiError> {
    app.transfers
        .clone()
        .try_acquire_owned()
        .map_err(|_| ApiError(openworker_store_postgres::SubmissionError::QueueFull.into()))
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Register {
    request_id: String,
    turn_id: String,
    name: String,
    content_type: String,
    size: u64,
    sha256: String,
}
pub(crate) async fn register(
    Extension(app): Extension<App>,
    Path(sid): Path<String>,
    Json(body): Json<Register>,
) -> Result<Response, ApiError> {
    let store = enabled(&app)?;
    let a = app.store.register_artifact(
        Registration {
            request_id: body.request_id,
            session_id: sid,
            turn_id: body.turn_id,
            name: body.name,
            content_type: body.content_type,
            expected: Expected {
                size: body.size,
                sha256: body.sha256,
            },
        },
        store.binding().clone(),
        &app.actor,
    )?;
    Ok((StatusCode::ACCEPTED, Json(public(&a))).into_response())
}
pub(crate) async fn list(
    Extension(app): Extension<App>,
    Path(sid): Path<String>,
) -> Result<Json<Value>, ApiError> {
    enabled(&app)?;
    Ok(Json(
        json!({"artifacts":app.store.artifacts(&sid)?.iter().map(public).collect::<Vec<_>>() }),
    ))
}
pub(crate) async fn metadata(
    Extension(app): Extension<App>,
    Path((sid, id)): Path<(String, String)>,
) -> Result<Json<Value>, ApiError> {
    enabled(&app)?;
    Ok(Json(public(&app.store.artifact(&sid, &id)?)))
}
pub(crate) async fn upload(
    Extension(app): Extension<App>,
    Path((sid, id)): Path<(String, String)>,
    request: Request,
) -> Result<Json<Value>, ApiError> {
    let store = enabled(&app)?;
    let _permit = transfer(&app)?;
    let a = app.store.artifact(&sid, &id)?;
    if let Some(n) = request.headers().get(header::CONTENT_LENGTH) {
        if n.to_str().ok().and_then(|v| v.parse::<u64>().ok()) != Some(a.registration.expected.size)
        {
            return Err(ApiError(Error::Conflict.into()));
        }
    }
    let gate = app.store.clone();
    let session = sid.clone();
    let input = tokio_util::io::StreamReader::new(Box::pin(
        request
            .into_body()
            .into_data_stream()
            .map_err(|_| std::io::Error::other("Artifact upload disconnected"))
            .and_then(move |bytes| {
                let gate = gate.clone();
                let session = session.clone();
                async move {
                    gate.authorize(
                        openworker_store_postgres::auth::Action::Artifact,
                        Some(&session),
                        None,
                    )
                    .map_err(|_| std::io::Error::other("Artifact permission unavailable"))?;
                    Ok(bytes)
                }
            }),
    ));
    let proof = tokio::time::timeout(Duration::from_secs(120), store.put(&a, input, &app.stop))
        .await
        .map_err(|_| ApiError(Error::Unavailable.into()))??;
    Ok(Json(public(
        &app.store.publish_artifact(&sid, &id, proof, &app.actor)?,
    )))
}
pub(crate) async fn reconcile(
    Extension(app): Extension<App>,
    Path((sid, id)): Path<(String, String)>,
) -> Result<Json<Value>, ApiError> {
    let store = enabled(&app)?;
    let _permit = transfer(&app)?;
    let a = app.store.artifact(&sid, &id)?;
    let proof = tokio::time::timeout(Duration::from_secs(120), store.verify(&a, &app.stop))
        .await
        .map_err(|_| ApiError(Error::Unavailable.into()))??;
    Ok(Json(public(
        &app.store.publish_artifact(&sid, &id, proof, &app.actor)?,
    )))
}
pub(crate) async fn download(
    Extension(app): Extension<App>,
    Path((sid, id)): Path<(String, String)>,
) -> Result<Response, ApiError> {
    let store = enabled(&app)?;
    let permit = transfer(&app)?;
    let a = app.store.artifact(&sid, &id)?;
    if a.status != Status::Ready {
        return Err(ApiError(Error::NotReady.into()));
    }
    let proof = a
        .proof
        .as_ref()
        .ok_or_else(|| ApiError(Error::Conflict.into()))?;
    let mut content = store.get(&a, proof, app.stop.clone()).await?;
    let stream = async_stream::stream! {let _permit=permit;use futures_util::StreamExt;while let Some(chunk)=content.next().await{
    if app.store.authorize(openworker_store_postgres::auth::Action::Read,Some(&sid),None).is_err(){yield Err(std::io::Error::other("Artifact permission unavailable"));break;}
    yield chunk.map_err(|_|std::io::Error::other("Artifact content unavailable or changed"));}};
    Response::builder()
        .header(header::CONTENT_TYPE, &a.registration.content_type)
        .header(header::CONTENT_LENGTH, a.registration.expected.size)
        .header(
            header::CONTENT_DISPOSITION,
            format!("attachment; filename=\"{}.bin\"", a.id),
        )
        .header(header::CACHE_CONTROL, "no-store")
        .header("x-content-type-options", "nosniff")
        .header("content-security-policy", "sandbox; default-src 'none'")
        .header(
            header::ETAG,
            format!("\"{}\"", a.registration.expected.sha256),
        )
        .body(Body::from_stream(stream))
        .map_err(|_| ApiError(Error::Unavailable.into()))
}
