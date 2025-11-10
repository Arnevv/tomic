'use strict';

const { test, beforeEach } = require('node:test');
const assert = require('assert');
const { EventEmitter } = require('events');
const { TwsConnection } = require('../scripts/tws-connection');

const wait = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

function createMockNet(sequence) {
  let attempt = 0;
  return {
    connect(_options, connectionListener) {
      const socket = new EventEmitter();
      socket.destroyed = false;
      socket.destroy = () => {
        if (!socket.destroyed) {
          socket.destroyed = true;
          socket.emit('close');
        }
      };

      setImmediate(() => {
        const behavior = sequence[attempt] ?? 'success';
        attempt += 1;

        if (behavior === 'error') {
          socket.emit('error', new Error('connection failed'));
          return;
        }

        connectionListener();
      });

      return socket;
    },
  };
}

let events;

beforeEach(() => {
  events = [];
});

test('retries once and succeeds on the next attempt', async () => {
  const connection = new TwsConnection({
    net: createMockNet(['error', 'success']),
    reconnectIntervalMs: 1,
    maxRetries: 2,
  });

  connection.on('reconnecting', (attempt) => events.push({ type: 'reconnecting', attempt }));
  connection.on('connected', () => events.push({ type: 'connected' }));

  await connection.connect();

  assert.strictEqual(connection.isConnected(), true, 'Connection should be established');
  assert.deepStrictEqual(events, [
    { type: 'reconnecting', attempt: 1 },
    { type: 'connected' },
  ]);

  await connection.disconnect();
});

test('attempts to reconnect after the socket closes', async () => {
  const connection = new TwsConnection({
    net: createMockNet(['success', 'success']),
    reconnectIntervalMs: 1,
    maxRetries: 2,
  });

  let connectedCount = 0;
  connection.on('connected', () => {
    events.push({ type: 'connected' });
    connectedCount += 1;
  });

  await connection.connect();
  assert.strictEqual(connection.isConnected(), true, 'initial connection should succeed');
  assert.strictEqual(connectedCount, 1);

  // Simulate a dropped connection.
  connection._socket.emit('close');

  // Allow the reconnection loop to run.
  await wait(5);

  assert.strictEqual(connection.isConnected(), true, 'connection should be re-established after close');
  assert.strictEqual(connectedCount, 2, 'connected event should fire twice');
  assert.deepStrictEqual(events, [{ type: 'connected' }, { type: 'connected' }]);

  await connection.disconnect();
});
