//! Persistent EDB store backed by sled.
//!
//! The EDB store provides:
//! - Append-only event log
//! - Materialized views of current facts, rules, and predicates per branch
//! - Visibility filtering (events up to a given watermark)
//! - Retraction support (marks facts as retracted without deleting events)

use std::collections::{HashMap, HashSet};
use std::convert::TryInto;
use std::fmt;
use std::path::Path;

use sled::{Db, Tree};

use doxa_core::rule::Rule;
use doxa_core::types::SymId;

use crate::event_log::{EdbEvent, EventId};

/// EDB error type.
#[derive(Debug)]
pub enum EdbError {
    Sled(sled::Error),
    Bincode(Box<bincode::ErrorKind>),
    UnknownBranch(String),
    EventNotFound(EventId),
}

impl fmt::Display for EdbError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EdbError::Sled(e) => write!(f, "sled error: {}", e),
            EdbError::Bincode(e) => write!(f, "bincode error: {}", e),
            EdbError::UnknownBranch(name) => write!(f, "unknown branch: {}", name),
            EdbError::EventNotFound(id) => write!(f, "event not found: {}", id),
        }
    }
}

impl std::error::Error for EdbError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            EdbError::Sled(e) => Some(e),
            EdbError::Bincode(e) => Some(e.as_ref()),
            _ => None,
        }
    }
}

impl From<sled::Error> for EdbError {
    fn from(e: sled::Error) -> Self {
        EdbError::Sled(e)
    }
}

impl From<Box<bincode::ErrorKind>> for EdbError {
    fn from(e: Box<bincode::ErrorKind>) -> Self {
        EdbError::Bincode(e)
    }
}

pub type Result<T> = std::result::Result<T, EdbError>;

/// A ground fact as materialized from the event log.
#[derive(Debug, Clone)]
pub struct GroundFact {
    pub event_id: EventId,
    pub pred_name: String,
    pub pred_arity: usize,
    pub args: Vec<SymId>,
    pub b: f64,
    pub d: f64,
    pub source: Option<String>,
    pub retracted: bool,
}

/// The persistent EDB store.
pub struct EdbStore {
    db: Db,
    /// Append-only event log. Key = event_id (u64 BE), value = serialized EdbEvent.
    event_tree: Tree,
    /// Metadata tree for counters etc.
    meta: Tree,
}

impl EdbStore {
    const NEXT_EVENT_KEY: &'static [u8] = b"next_event_id";

    /// Open or create an EDB store at the given path.
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let db = sled::open(path.as_ref())?;
        Self::from_db(db)
    }

    /// Create a temporary in-memory EDB store (no filesystem I/O).
    pub fn open_temporary() -> Result<Self> {
        let db = sled::Config::new().temporary(true).open()?;
        Self::from_db(db)
    }

    fn from_db(db: Db) -> Result<Self> {
        let event_tree = db.open_tree("edb_events")?;
        let meta = db.open_tree("edb_meta")?;

        if meta.get(Self::NEXT_EVENT_KEY)?.is_none() {
            meta.insert(Self::NEXT_EVENT_KEY, 1u64.to_be_bytes().as_slice())?;
        }

        Ok(Self {
            db,
            event_tree,
            meta,
        })
    }

    /// Flush all trees to disk.
    pub fn flush_all(&self) -> Result<()> {
        self.event_tree.flush()?;
        self.meta.flush()?;
        self.db.flush()?;
        Ok(())
    }

    /// Allocate the next event ID atomically.
    fn next_event_id(&self) -> Result<EventId> {
        let old = self.meta.fetch_and_update(Self::NEXT_EVENT_KEY, |old| {
            let current = u64::from_be_bytes(old.unwrap().try_into().unwrap());
            Some(Vec::from((current + 1).to_be_bytes()))
        })?;
        let id = u64::from_be_bytes(old.unwrap().as_ref().try_into().unwrap());
        Ok(id)
    }

    /// Append an event to the log. The event_id field in the event is set
    /// by this method. Returns the assigned event ID.
    fn append_event(&self, event: &EdbEvent) -> Result<EventId> {
        let eid = event.event_id();
        let key = eid.to_be_bytes();
        let val = bincode::serialize(event)?;
        self.event_tree.insert(key.as_slice(), val.as_slice())?;
        Ok(eid)
    }

    /// Assert a ground fact. Returns the event ID.
    pub fn assert_fact(
        &self,
        branch: &str,
        pred_name: &str,
        pred_arity: usize,
        args: Vec<SymId>,
        b: f64,
        d: f64,
        source: Option<String>,
    ) -> Result<EventId> {
        let event_id = self.next_event_id()?;
        let event = EdbEvent::AssertFact {
            event_id,
            branch: branch.to_string(),
            pred_name: pred_name.to_string(),
            pred_arity,
            args,
            b,
            d,
            source,
        };
        self.append_event(&event)
    }

    /// Declare a predicate. Returns the event ID.
    pub fn declare_predicate(
        &self,
        branch: &str,
        pred_name: &str,
        pred_arity: usize,
    ) -> Result<EventId> {
        let event_id = self.next_event_id()?;
        let event = EdbEvent::DeclarePredicate {
            event_id,
            branch: branch.to_string(),
            pred_name: pred_name.to_string(),
            pred_arity,
        };
        self.append_event(&event)
    }

    /// Add a rule. Returns the event ID.
    pub fn add_rule(&self, branch: &str, rule: Rule) -> Result<EventId> {
        let event_id = self.next_event_id()?;
        let event = EdbEvent::AddRule {
            event_id,
            branch: branch.to_string(),
            rule,
        };
        self.append_event(&event)
    }

    /// Retract a previously asserted fact by its original event ID.
    pub fn retract_fact(
        &self,
        branch: &str,
        target_event_id: EventId,
    ) -> Result<EventId> {
        let event_id = self.next_event_id()?;
        let event = EdbEvent::RetractFact {
            event_id,
            branch: branch.to_string(),
            target_event_id,
        };
        self.append_event(&event)
    }

    /// Scan the event log and return all visible ground facts for a branch,
    /// considering retractions. Only events with `event_id <= watermark`
    /// are included.
    pub fn get_facts(
        &self,
        branch: &str,
        watermark: Option<EventId>,
    ) -> Result<Vec<GroundFact>> {
        let mut facts: HashMap<EventId, GroundFact> = HashMap::new();
        let mut retracted: HashSet<EventId> = HashSet::new();

        for item in self.event_tree.iter() {
            let (_key_bytes, val_bytes) = item?;
            let event: EdbEvent = bincode::deserialize(val_bytes.as_ref())?;

            if let Some(wm) = watermark {
                if event.event_id() > wm {
                    break; // events are ordered by ID
                }
            }

            if event.branch() != branch {
                continue;
            }

            match &event {
                EdbEvent::AssertFact {
                    event_id,
                    pred_name,
                    pred_arity,
                    args,
                    b,
                    d,
                    source,
                    ..
                } => {
                    facts.insert(
                        *event_id,
                        GroundFact {
                            event_id: *event_id,
                            pred_name: pred_name.clone(),
                            pred_arity: *pred_arity,
                            args: args.clone(),
                            b: *b,
                            d: *d,
                            source: source.clone(),
                            retracted: false,
                        },
                    );
                }
                EdbEvent::RetractFact {
                    target_event_id, ..
                } => {
                    retracted.insert(*target_event_id);
                }
                _ => {}
            }
        }

        Ok(facts
            .into_iter()
            .filter(|(id, _)| !retracted.contains(id))
            .map(|(_, f)| f)
            .collect())
    }

    /// Return all rules for a branch (up to watermark).
    pub fn get_rules(
        &self,
        branch: &str,
        watermark: Option<EventId>,
    ) -> Result<Vec<Rule>> {
        let mut rules = Vec::new();

        for item in self.event_tree.iter() {
            let (_, val_bytes) = item?;
            let event: EdbEvent = bincode::deserialize(val_bytes.as_ref())?;

            if let Some(wm) = watermark {
                if event.event_id() > wm {
                    break;
                }
            }

            if event.branch() != branch {
                continue;
            }

            if let EdbEvent::AddRule { rule, .. } = event {
                rules.push(rule);
            }
        }

        Ok(rules)
    }

    /// Return all declared predicates for a branch (name, arity).
    pub fn get_predicates(
        &self,
        branch: &str,
        watermark: Option<EventId>,
    ) -> Result<Vec<(String, usize)>> {
        let mut preds = Vec::new();

        for item in self.event_tree.iter() {
            let (_, val_bytes) = item?;
            let event: EdbEvent = bincode::deserialize(val_bytes.as_ref())?;

            if let Some(wm) = watermark {
                if event.event_id() > wm {
                    break;
                }
            }

            if event.branch() != branch {
                continue;
            }

            if let EdbEvent::DeclarePredicate {
                pred_name,
                pred_arity,
                ..
            } = event
            {
                preds.push((pred_name, pred_arity));
            }
        }

        Ok(preds)
    }

    /// Return the current watermark (highest event ID written).
    pub fn current_watermark(&self) -> Result<EventId> {
        let next = u64::from_be_bytes(
            self.meta
                .get(Self::NEXT_EVENT_KEY)?
                .unwrap()
                .as_ref()
                .try_into()
                .unwrap(),
        );
        Ok(if next > 1 { next - 1 } else { 0 })
    }

    /// Return events since a given event ID (exclusive), up to watermark.
    /// Useful for delta-based incremental recomputation.
    pub fn get_events_since(
        &self,
        since: EventId,
        watermark: Option<EventId>,
    ) -> Result<Vec<EdbEvent>> {
        let mut events = Vec::new();
        let start_key = (since + 1).to_be_bytes();

        for item in self.event_tree.range(start_key.as_slice()..) {
            let (_, val_bytes) = item?;
            let event: EdbEvent = bincode::deserialize(val_bytes.as_ref())?;

            if let Some(wm) = watermark {
                if event.event_id() > wm {
                    break;
                }
            }

            events.push(event);
        }

        Ok(events)
    }
}
