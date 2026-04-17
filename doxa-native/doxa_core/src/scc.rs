//! Strongly Connected Component (SCC) analysis for the predicate
//! dependency graph. Used by the engine to determine evaluation order.

use std::collections::{HashMap, HashSet};

use crate::rule::Rule;
use crate::types::PredId;

/// A node in the predicate dependency graph.
#[derive(Debug, Clone)]
pub struct DepNode {
    pub pred_name: String,
    pub pred_id: Option<PredId>,
}

/// One strongly connected component in the predicate dependency graph.
#[derive(Debug, Clone)]
pub struct Scc {
    /// Index of this SCC in topological order (0 = leaves).
    pub index: usize,
    /// Predicate names in this SCC.
    pub predicates: Vec<String>,
    /// Whether this SCC is recursive (has a cycle).
    pub recursive: bool,
}

/// Build the predicate dependency graph from a set of rules and compute
/// SCCs in reverse topological order (leaves first, roots last).
///
/// Returns SCCs ordered so that if SCC A depends on SCC B, then B
/// appears before A in the returned vector.
pub fn compute_sccs(rules: &[Rule]) -> Vec<Scc> {
    // 1. Build adjacency list: head_pred -> set of body preds
    let mut preds: HashSet<String> = HashSet::new();
    let mut edges: HashMap<String, HashSet<String>> = HashMap::new();

    for rule in rules {
        preds.insert(rule.head_pred_name.clone());
        let entry = edges
            .entry(rule.head_pred_name.clone())
            .or_insert_with(HashSet::new);
        for goal in &rule.body {
            match goal {
                crate::rule::Goal::Atom(ag) if !ag.negated => {
                    preds.insert(ag.pred_name.clone());
                    entry.insert(ag.pred_name.clone());
                }
                _ => {}
            }
        }
    }

    // Ensure all preds have an entry
    for p in &preds {
        edges.entry(p.clone()).or_insert_with(HashSet::new);
    }

    // 2. Tarjan's SCC algorithm
    let pred_list: Vec<String> = preds.into_iter().collect();
    let idx_map: HashMap<&str, usize> = pred_list
        .iter()
        .enumerate()
        .map(|(i, p)| (p.as_str(), i))
        .collect();
    let n = pred_list.len();

    let adj: Vec<Vec<usize>> = pred_list
        .iter()
        .map(|p| {
            edges
                .get(p)
                .map(|deps| {
                    deps.iter()
                        .filter_map(|d| idx_map.get(d.as_str()).copied())
                        .collect()
                })
                .unwrap_or_default()
        })
        .collect();

    let mut index_counter: usize = 0;
    let mut stack: Vec<usize> = Vec::new();
    let mut on_stack = vec![false; n];
    let mut indices = vec![usize::MAX; n];
    let mut lowlinks = vec![0usize; n];
    let mut result: Vec<Vec<usize>> = Vec::new();

    fn strongconnect(
        v: usize,
        adj: &[Vec<usize>],
        index_counter: &mut usize,
        stack: &mut Vec<usize>,
        on_stack: &mut [bool],
        indices: &mut [usize],
        lowlinks: &mut [usize],
        result: &mut Vec<Vec<usize>>,
    ) {
        indices[v] = *index_counter;
        lowlinks[v] = *index_counter;
        *index_counter += 1;
        stack.push(v);
        on_stack[v] = true;

        for &w in &adj[v] {
            if indices[w] == usize::MAX {
                strongconnect(
                    w,
                    adj,
                    index_counter,
                    stack,
                    on_stack,
                    indices,
                    lowlinks,
                    result,
                );
                lowlinks[v] = lowlinks[v].min(lowlinks[w]);
            } else if on_stack[w] {
                lowlinks[v] = lowlinks[v].min(indices[w]);
            }
        }

        if lowlinks[v] == indices[v] {
            let mut component = Vec::new();
            loop {
                let w = stack.pop().unwrap();
                on_stack[w] = false;
                component.push(w);
                if w == v {
                    break;
                }
            }
            result.push(component);
        }
    }

    for v in 0..n {
        if indices[v] == usize::MAX {
            strongconnect(
                v,
                &adj,
                &mut index_counter,
                &mut stack,
                &mut on_stack,
                &mut indices,
                &mut lowlinks,
                &mut result,
            );
        }
    }

    // Tarjan naturally produces SCCs with sinks (leaves) first, which is
    // exactly the bottom-up evaluation order we need.
    result
        .into_iter()
        .enumerate()
        .map(|(i, component)| {
            let predicates: Vec<String> = component
                .iter()
                .map(|&idx| pred_list[idx].clone())
                .collect();
            // Recursive if component has >1 node, or a self-loop
            let recursive = component.len() > 1 || component.iter().any(|&v| adj[v].contains(&v));
            Scc {
                index: i,
                predicates,
                recursive,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rule::{AtomGoal, Goal, Rule};
    use crate::types::Term;

    fn make_rule(head: &str, arity: usize, body_preds: &[&str]) -> Rule {
        let body = body_preds
            .iter()
            .map(|&p| {
                Goal::Atom(AtomGoal {
                    pred_name: p.to_string(),
                    pred_arity: 1,
                    negated: false,
                    args: vec![Term::Var("X".to_string())],
                })
            })
            .collect();
        Rule {
            id: 0,
            head_pred_name: head.to_string(),
            head_pred_arity: arity,
            head_args: vec![Term::Var("X".to_string())],
            body,
            b: 1.0,
            d: 0.0,
        }
    }

    #[test]
    fn test_linear_chain() {
        // c :- b. b :- a.
        let rules = vec![make_rule("c", 1, &["b"]), make_rule("b", 1, &["a"])];
        let sccs = compute_sccs(&rules);
        // a, b, c should each be in their own SCC, none recursive
        assert_eq!(sccs.len(), 3);
        for scc in &sccs {
            assert!(!scc.recursive);
            assert_eq!(scc.predicates.len(), 1);
        }
        // a should come before b, b before c
        let pos = |name: &str| {
            sccs.iter()
                .position(|s| s.predicates.contains(&name.to_string()))
                .unwrap()
        };
        assert!(pos("a") < pos("b"));
        assert!(pos("b") < pos("c"));
    }

    #[test]
    fn test_mutual_recursion() {
        // a :- b. b :- a.
        let rules = vec![make_rule("a", 1, &["b"]), make_rule("b", 1, &["a"])];
        let sccs = compute_sccs(&rules);
        assert_eq!(sccs.len(), 1);
        assert!(sccs[0].recursive);
        assert_eq!(sccs[0].predicates.len(), 2);
    }

    #[test]
    fn test_self_recursion() {
        // a :- a.
        let rules = vec![make_rule("a", 1, &["a"])];
        let sccs = compute_sccs(&rules);
        assert_eq!(sccs.len(), 1);
        assert!(sccs[0].recursive);
    }
}
