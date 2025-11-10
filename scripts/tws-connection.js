'use strict';

const net = require('net');
const { EventEmitter } = require('events');

const DEFAULT_CONFIG = {
  host: process.env.TWS_HOST || '127.0.0.1',
  port: Number(process.env.TWS_PORT) || 7497,
  clientId: Number(process.env.TWS_CLIENT_ID) || 0,
  reconnectIntervalMs: 1_000,
  maxRetries: 10,
};

class TwsConnection extends EventEmitter {
  constructor(config = {}) {
    super();

    const merged = { ...DEFAULT_CONFIG, ...config };
    this.host = merged.host;
    this.port = merged.port;
    this.clientId = merged.clientId;
    this.reconnectIntervalMs = merged.reconnectIntervalMs;
    this.maxRetries = merged.maxRetries;
    this._net = merged.net || net;

    this._socket = null;
    this._connected = false;
    this._retries = 0;
    this._stopped = false;
    this._reconnectPromise = null;
  }

  async connect() {
    this._stopped = false;
    this._retries = 0;

    return this._connectWithRetry();
  }

  async _connectWithRetry() {
    while (!this._stopped) {
      try {
        await this._connectOnce();
        return;
      } catch (error) {
        this._retries += 1;
        if (this.maxRetries !== 0 && this._retries > this.maxRetries) {
          this.emit('reconnect_failed', error);
          throw error;
        }
        this.emit('reconnecting', this._retries, error);
        await this._delay(this.reconnectIntervalMs);
      }
    }
  }

  _connectOnce() {
    return new Promise((resolve, reject) => {
      const socket = this._net.connect({ host: this.host, port: this.port }, () => {
        this._socket = socket;
        this._connected = true;
        this._retries = 0;
        this.emit('connected', { host: this.host, port: this.port, clientId: this.clientId });

        socket.once('close', () => {
          this._connected = false;
          if (this._stopped) {
            return;
          }
          this.emit('disconnected');
          this._triggerReconnectLoop();
        });

        socket.on('error', (err) => {
          this._emitError(err);
        });

        resolve();
      });

      socket.once('error', (err) => {
        socket.destroy();
        this._emitError(err);
        reject(err);
      });
    });
  }

  _triggerReconnectLoop() {
    if (this._reconnectPromise || this._stopped) {
      return;
    }

    this._reconnectPromise = (async () => {
      try {
        await this._connectWithRetry();
      } catch (error) {
        // Error already emitted in _connectWithRetry; surface final failure as well.
        this.emit('reconnect_failed', error);
      } finally {
        this._reconnectPromise = null;
      }
    })();
  }

  isConnected() {
    return this._connected;
  }

  async disconnect() {
    this._stopped = true;
    if (this._reconnectPromise) {
      try {
        await this._reconnectPromise;
      } catch (error) {
        // ignore errors when shutting down
        void error;
      }
    }

    if (this._socket) {
      this._socket.destroy();
      this._socket = null;
    }

    this._connected = false;
  }

  _delay(ms) {
    return new Promise((resolve) => {
      setTimeout(resolve, ms);
    });
  }

  _emitError(err) {
    if (this.listenerCount('error') > 0) {
      this.emit('error', err);
    }
  }
}

function createConnection(config) {
  const connection = new TwsConnection(config);
  connection.connect().catch((error) => {
    connection.emit('reconnect_failed', error);
  });
  return connection;
}

module.exports = {
  DEFAULT_CONFIG,
  TwsConnection,
  createConnection,
};
