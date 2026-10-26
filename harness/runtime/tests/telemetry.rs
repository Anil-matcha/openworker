#![cfg(any(windows, target_os = "linux"))]
use openworker_runtime::{execution::Backend, model::Model, runtime::Runtime, telemetry::*};
use openworker_tools::{Tool, ToolContext, ToolDescriptor, ToolFuture, ToolOutput, ToolRegistry};
use serde_json::{json, Value};
use std::{
    path::Path,
    sync::{Arc, Mutex},
    time::Duration,
};
struct Capture(Arc<Mutex<Vec<Record>>>);
impl Sink for Capture {
    fn export(&mut self, r: &[Record], _: Snapshot) -> bool {
        self.0.lock().unwrap().extend_from_slice(r);
        true
    }
}
struct SecretTool;
impl Tool for SecretTool {
    fn descriptor(&self) -> ToolDescriptor {
        ToolDescriptor {
            qualified_name: "private.probe".into(),
            description: "SENSITIVE_DESCRIPTION".into(),
            version: "1".into(),
            input_schema: json!({"type":"object","properties":{"secret":{"type":"string"}},"required":["secret"],"additionalProperties":false}),
        }
    }
    fn call(&self, _: ToolContext, _: Value) -> ToolFuture<'_> {
        Box::pin(async { Ok(ToolOutput::json(json!({"result":"SENSITIVE_TOOL_OUTPUT"}))) })
    }
}
async fn wait(rt: &Arc<Runtime>, sid: &str, state: &str) -> Value {
    tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            let v = rt.snapshot(sid).unwrap();
            if v["turn"]["status"] == state && !rt.is_busy(sid) {
                return v;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .unwrap()
}
#[tokio::test(flavor = "multi_thread")]
async fn actual_agent_approval_resume_has_hierarchy_without_exporting_content() {
    let root = tempfile::tempdir().unwrap();
    let bundle = root.path().join("bundle");
    std::fs::create_dir_all(bundle.join("coworker")).unwrap();
    std::fs::create_dir(root.path().join("work")).unwrap();
    std::fs::write(
        bundle.join("coworker/manifest.md"),
        "---\nid: trace-test\nname: Trace Test\n---\nSENSITIVE_INSTRUCTIONS",
    )
    .unwrap();
    std::fs::write(
        bundle.join("tools.json"),
        r#"{"version":3,"tools":["private.probe"]}"#,
    )
    .unwrap();
    let mut registry = ToolRegistry::default();
    registry.register(SecretTool).unwrap();
    let rows = Arc::new(Mutex::new(vec![]));
    let (telemetry, controller) = Telemetry::start(Capture(rows.clone()), 2048).unwrap();
    let rt = Runtime::open_instrumented(
        &root.path().join("state"),
        &bundle,
        Path::new(env!("CARGO_BIN_EXE_openworker")),
        Model::new("fixture".into(), true),
        Backend::Off,
        None,
        None,
        registry,
        None,
        telemetry,
    )
    .unwrap();
    let s=rt.dispatch("session/create",json!({"name":"SENSITIVE_NAME","coworker":"trace-test","workspace":root.path().join("work")})).await.unwrap();
    let sid = s["session"]["id"].as_str().unwrap();
    for (n, decision) in [(0, "once"), (1, "deny")] {
        let steps = json!([{"name":"private__probe","arguments":{"secret":"SENSITIVE_ARGUMENT"}}]);
        rt.dispatch("turn/start",json!({"session_id":sid,"submission_id":format!("request-{n}"),"text":format!("TEST_RESOURCE_GRANTS {steps}")})).await.unwrap();
        let waiting = wait(&rt, sid, "waiting").await;
        let id = &waiting["interactions"][0]["id"];
        rt.dispatch(
            "interaction/respond",
            json!({"session_id":sid,"interaction_id":id,"decision":decision}),
        )
        .await
        .unwrap();
        wait(&rt, sid, "completed").await;
    }
    rt.shutdown().await.unwrap();
    assert!(controller.shutdown(Duration::from_secs(3)));
    let rows = rows.lock().unwrap();
    assert!(!format!("{rows:?}").contains("SENSITIVE"));
    assert!(!format!("{rows:?}").contains(sid));
    let tool = rows
        .iter()
        .filter(|r| r.operation == Operation::Tool)
        .collect::<Vec<_>>();
    assert_eq!(tool.len(), 1);
    assert_eq!(tool[0].outcome, Outcome::Ok);
    let parent = tool[0].parent.unwrap();
    assert!(rows
        .iter()
        .any(|r| r.context == parent && r.operation == Operation::Turn));
    assert_eq!(
        rows.iter()
            .filter(|r| r.operation == Operation::Turn && r.outcome == Outcome::Waiting)
            .count(),
        2
    );
    assert!(rows
        .iter()
        .any(|r| r.operation == Operation::ApprovalResolved && r.outcome == Outcome::Denied));
    assert!(rows.iter().any(|r| r.operation == Operation::Model));
    assert!(rows.iter().all(|r| r.input_tokens.is_none()));
}
