//! Regression experiment for https://github.com/n0-computer/noq/issues/841
//! Derived from the original issue's published reproducer (with attribution).
//! The machine sleep is simulated by advancing the virtual clock. No real sleep needed.

use std::{sync::mpsc, time::Duration, vec::Vec};

use super::util::ConnPair;
use crate::{Dir, Side::*};

/// Incoming data on wake resets idle, but the old loss timer is re-armed in the past.
/// Before the fix, handle_timeout keeps processing the same timer indefinitely.
#[test]
fn handle_timeout_returns_after_long_stall() {
    let mut pair = ConnPair::builder().connect();

    // Keep an outgoing packet unacknowledged when the machine goes to sleep.
    let stream = pair.streams(Client).open(Dir::Uni).unwrap();
    pair.send_stream(Client, stream)
        .write(&[0; 1000])
        .unwrap();
    pair.drive_client();
    pair.server.inbound.clear(); // Lost while sleeping.

    // A packet from the peer arrives only when the computer wakes.
    let stream = pair.streams(Server).open(Dir::Uni).unwrap();
    pair.send_stream(Server, stream)
        .write(&[0; 100])
        .unwrap();
    pair.drive_server();

    pair.time += Duration::from_secs(3 * 60 * 60);
    let now = pair.time;
    let held: Vec<_> = std::iter::from_fn(|| pair.client.inbound.pop_first()).collect();
    for (_, packet) in held {
        pair.client.inbound.push(now, packet);
    }
    pair.client.drive_incoming(now);

    // Mirror the driver order: peer packets, then expired timers.
    let handle = *pair.client.connections.keys().next().unwrap();
    let mut conn = pair.client.connections.remove(&handle).unwrap();
    for event in pair.client.conn_events.drain().flat_map(|(_, e)| e) {
        conn.handle_event(event);
    }

    // This separate thread bounds the test even if handle_timeout never returns.
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        conn.handle_timeout(now);
        let _ = tx.send(());
    });
    rx.recv_timeout(Duration::from_secs(10))
        .expect("handle_timeout never returned after simulated sleep");
}
