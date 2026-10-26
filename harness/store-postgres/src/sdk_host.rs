//! SDK-managed execution ownership. One host per schema; PostgreSQL durability
//! does not imply that an embedded SDK has enabled distributed scheduling.
use crate::db::Database;
use anyhow::{ensure, Result};
impl Database {
    pub(crate) fn claim_sdk_host(&mut self, coworkers: &[String]) -> Result<()> {
        ensure!(
            self.leases.is_empty(),
            "SDK host must claim before starting sessions"
        );
        let locked: bool = self
            .client
            .query_one(
                "SELECT pg_try_advisory_lock(hashtext(current_schema()), 18475001)",
                &[],
            )?
            .get(0);
        ensure!(locked, "Another SDK host owns this PostgreSQL schema");
        let mut tx = self.client.transaction()?;
        let marked: bool = tx
            .query_one("SELECT EXISTS(SELECT 1 FROM sdk_host_mode)", &[])?
            .get(0);
        if !marked {
            let empty: bool = tx
                .query_one("SELECT NOT EXISTS(SELECT 1 FROM sessions)", &[])?
                .get(0);
            ensure!(empty,"Use a fresh PostgreSQL schema for SDK-managed execution; distributed sessions cannot be silently adopted");
            tx.execute("INSERT INTO sdk_host_mode VALUES(TRUE,'sdk')", &[])?;
        }
        let valid:bool=tx.query_one("SELECT NOT EXISTS(SELECT 1 FROM sessions WHERE NOT (data->>'coworker'=ANY($1)) OR data ? 'environment')",&[&coworkers])?.get(0);
        ensure!(
            valid,
            "SDK coworker configuration does not cover persisted sessions"
        );
        // Holding this connection-level lock proves any previous SDK database
        // connection has closed. Fence its epochs before recovery, retaining
        // uncertain effects rather than replaying them.
        tx.execute("UPDATE sessions SET expires=clock_timestamp()", &[])?;
        let ids: Vec<String> = tx
            .query("SELECT id FROM sessions ORDER BY id", &[])?
            .into_iter()
            .map(|r| r.get(0))
            .collect();
        tx.commit()?;
        for id in ids {
            self.claim(&id)?;
        }
        Ok(())
    }
}
