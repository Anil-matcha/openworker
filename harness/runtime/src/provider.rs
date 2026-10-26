//! Typed, sanitized Responses outcomes. This module never retries or executes tools.
use crate::model::{validate_output, Progress};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::sync::mpsc;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize, clap::ValueEnum)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    #[default]
    Openai,
    Anthropic,
}
impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Self::Openai => "openai",
            Self::Anthropic => "anthropic",
        }
    }
    pub fn key_env(self) -> &'static str {
        match self {
            Self::Openai => "OPENAI_API_KEY",
            Self::Anthropic => "ANTHROPIC_API_KEY",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Failure {
    RateLimit,
    Transient,
    Transport,
    IncompleteStream,
    InvalidResponse,
    ContextOverflow,
    Truncated,
    Authentication,
    Configuration,
    SafetyBlocked,
}
#[derive(Clone, Debug)]
pub struct Error {
    pub kind: Failure,
    pub retry_after: Option<u64>,
    /// Set only on an HTTP rejection, never on an error inside a stream.
    pub http_status: Option<u16>,
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "Provider {:?}; no tool actions accepted from this attempt",
            self.kind
        )
    }
}
impl std::error::Error for Error {}
impl Error {
    pub fn new(kind: Failure) -> Self {
        Self {
            kind,
            retry_after: None,
            http_status: None,
        }
    }
    pub fn retryable(&self) -> bool {
        matches!(
            self.kind,
            Failure::RateLimit
                | Failure::Transient
                | Failure::Transport
                | Failure::IncompleteStream
        ) && self.retry_after.is_none_or(|s| s <= 30)
    }
}
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Usage {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cached_input_tokens: u64,
}
#[derive(Clone, Debug)]
pub struct Completion {
    pub output: Vec<Value>,
    pub usage: Option<Usage>,
}

pub fn classify(status: u16, code: &str) -> Failure {
    match code {
        "misalignment_policy_violation" => Failure::SafetyBlocked,
        "context_length_exceeded" => Failure::ContextOverflow,
        "rate_limit_exceeded" => Failure::RateLimit,
        "insufficient_quota" => Failure::Configuration,
        "invalid_api_key" | "authentication_error" => Failure::Authentication,
        "invalid_request_error" => Failure::Configuration,
        "server_error" => Failure::Transient,
        _ => match status {
            401 | 403 => Failure::Authentication,
            408 | 409 | 500 | 502 | 503 | 504 => Failure::Transient,
            429 => Failure::RateLimit,
            _ => Failure::Configuration,
        },
    }
}

/// Exposed as a pure seam for recorded-event and fault-injection tests.
#[derive(Default)]
pub struct Decoder {
    completion: Option<Completion>,
}
impl Decoder {
    pub fn event(&mut self, event: &Value) -> Result<Option<String>, Error> {
        if event["response"]["error"]["code"] == "misalignment_policy_violation"
            || event["code"] == "misalignment_policy_violation"
        {
            self.completion = None;
            return Err(Error::new(Failure::SafetyBlocked));
        }
        if self.completion.is_some() {
            return Err(Error::new(Failure::InvalidResponse));
        }
        match event["type"].as_str().unwrap_or("") {
            "response.output_text.delta" => Ok(Some(
                event["delta"]
                    .as_str()
                    .ok_or_else(|| Error::new(Failure::InvalidResponse))?
                    .to_owned(),
            )),
            "response.completed" => {
                let r = &event["response"];
                if r["status"] != "completed" {
                    return Err(Error::new(Failure::InvalidResponse));
                }
                let output = r["output"]
                    .as_array()
                    .cloned()
                    .ok_or_else(|| Error::new(Failure::InvalidResponse))?;
                if output.is_empty() || validate_output(&output).is_err() {
                    return Err(Error::new(Failure::InvalidResponse));
                }
                let usage = if r["usage"]["input_tokens"].is_u64()
                    && r["usage"]["output_tokens"].is_u64()
                {
                    Some(Usage {
                        input_tokens: r["usage"]["input_tokens"].as_u64().unwrap(),
                        output_tokens: r["usage"]["output_tokens"].as_u64().unwrap(),
                        cached_input_tokens: r["usage"]["input_tokens_details"]["cached_tokens"]
                            .as_u64()
                            .unwrap_or(0),
                    })
                } else {
                    None
                };
                self.completion = Some(Completion { output, usage });
                Ok(None)
            }
            "response.incomplete" => Err(Error::new(
                if event["response"]["incomplete_details"]["reason"] == "max_output_tokens" {
                    Failure::Truncated
                } else {
                    Failure::InvalidResponse
                },
            )),
            "response.failed" | "error" => {
                let code = event["response"]["error"]["code"]
                    .as_str()
                    .or(event["code"].as_str())
                    .unwrap_or("");
                Err(Error::new(classify(0, code)))
            }
            _ => Ok(None),
        }
    }
    pub fn finish(self) -> Result<Completion, Error> {
        self.completion
            .ok_or_else(|| Error::new(Failure::IncompleteStream))
    }
}

pub async fn request(
    client: &reqwest::Client,
    url: &str,
    key: &str,
    body: Value,
    tx: mpsc::Sender<Progress>,
) -> Result<(), Error> {
    request_decoded(client, url, key, body, tx, Decoder::default()).await
}

pub(crate) trait StreamDecoder {
    fn event(&mut self, value: &Value) -> Result<Option<String>, Error>;
    fn done(&mut self) -> Result<(), Error> {
        Ok(())
    }
    fn finish(self) -> Result<Completion, Error>;
}
impl StreamDecoder for Decoder {
    fn event(&mut self, value: &Value) -> Result<Option<String>, Error> {
        self.event(value)
    }
    fn finish(self) -> Result<Completion, Error> {
        self.finish()
    }
}
pub(crate) async fn request_decoded<D: StreamDecoder>(
    client: &reqwest::Client,
    url: &str,
    key: &str,
    body: Value,
    tx: mpsc::Sender<Progress>,
    mut decoder: D,
) -> Result<(), Error> {
    let request = client.post(url);
    let request = if key.is_empty() {
        request
    } else {
        request.bearer_auth(key)
    };
    let response = request
        .json(&body)
        .send()
        .await
        .map_err(|_| Error::new(Failure::Transport))?;
    if !response.status().is_success() {
        let status = response.status().as_u16();
        let retry_after = response
            .headers()
            .get("retry-after")
            .and_then(|h| h.to_str().ok())
            .and_then(|h| h.parse().ok());
        let mut stream = response.bytes_stream();
        let mut bytes = vec![];
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|_| Error::new(classify(status, "")))?;
            if bytes.len() + chunk.len() > 16384 {
                break;
            }
            bytes.extend_from_slice(&chunk);
        }
        let error: Value = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
        return Err(Error {
            kind: classify(status, error["error"]["code"].as_str().unwrap_or("")),
            retry_after,
            http_status: Some(status),
        });
    }
    let mut stream = response.bytes_stream();
    let mut buffer = vec![];
    let mut total = 0usize;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| Error::new(Failure::Transport))?;
        total += chunk.len();
        if total > 8 * 1024 * 1024 {
            return Err(Error::new(Failure::InvalidResponse));
        }
        buffer.extend_from_slice(&chunk);
        while let Some(i) = buffer.iter().position(|&c| c == b'\n') {
            let line = buffer.drain(..=i).collect::<Vec<_>>();
            let line = std::str::from_utf8(&line)
                .map_err(|_| Error::new(Failure::InvalidResponse))?
                .trim();
            let Some(data) = line.strip_prefix("data:") else {
                continue;
            };
            if data.trim() == "[DONE]" {
                decoder.done()?;
                continue;
            }
            let event: Value =
                serde_json::from_str(data).map_err(|_| Error::new(Failure::InvalidResponse))?;
            if let Some(text) = decoder.event(&event)? {
                tx.send(Progress::Delta(text))
                    .await
                    .map_err(|_| Error::new(Failure::Transport))?;
            }
        }
    }
    if !buffer.iter().all(u8::is_ascii_whitespace) {
        return Err(Error::new(Failure::InvalidResponse));
    }
    tx.send(Progress::Complete(decoder.finish()?))
        .await
        .map_err(|_| Error::new(Failure::Transport))?;
    Ok(())
}
