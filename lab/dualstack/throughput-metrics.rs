//! Instrumentacao exclusiva da copia de laboratorio; sem identidades ou segredos.
use std::sync::{OnceLock, atomic::{AtomicU64, Ordering::Relaxed}};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

pub fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| std::env::var("DS_LAB_METRICS").as_deref() == Ok("1"))
}
struct Metric { count: AtomicU64, ns: AtomicU64, max: AtomicU64 }
const fn metric() -> Metric { Metric { count: AtomicU64::new(0), ns: AtomicU64::new(0), max: AtomicU64::new(0) } }
static METRICS: [Metric; 13] = [const { metric() }; 13];
static COMMITTED: AtomicU64 = AtomicU64::new(0);
const NAMES: [&str; 13] = ["publish_wait", "publish_hold", "select_wait", "select_hold",
    "persist", "begin", "fence_and_reads", "apply", "peers", "endpoints", "history", "deltas", "commit"];
pub struct Span(usize, Option<Instant>);
impl Span { pub fn new(id: usize) -> Self { Self(id, enabled().then(Instant::now)) } }
impl Drop for Span {
    fn drop(&mut self) { if let Some(start) = self.1 { record(self.0, start.elapsed().as_nanos() as u64); } }
}
pub fn record(id: usize, ns: u64) {
    if !enabled() { return; }
    let m = &METRICS[id]; m.count.fetch_add(1, Relaxed); m.ns.fetch_add(ns, Relaxed); m.max.fetch_max(ns, Relaxed);
}
pub fn committed(n: usize) { COMMITTED.fetch_add(n as u64, Relaxed); }
pub fn emit(backlog: usize, retries: u64) {
    if !enabled() { return; }
    let values: serde_json::Map<String, serde_json::Value> = NAMES.iter().zip(METRICS.iter()).map(|(name, m)|
        (name.to_string(), serde_json::json!({"count":m.count.load(Relaxed),"ns":m.ns.load(Relaxed),"max_ns":m.max.load(Relaxed)}))).collect();
    eprintln!("DS_METRIC {}", serde_json::json!({"at":SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs_f64(),
        "backlog":backlog,"committed":COMMITTED.load(Relaxed),"retries":retries,"metrics":values}));
}
