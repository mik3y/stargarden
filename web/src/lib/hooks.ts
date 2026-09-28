import { useEffect, useRef, useState } from "react";

import {
  type FixturePreview,
  type LogLine,
  type Status,
  type StreamMessage,
  streamUrl,
} from "@/lib/api";

/** Lines kept in the log pane; the same as the server's ring buffer. */
const LOG_LIMIT = 500;
const RECONNECT_MS = [500, 1000, 2000, 5000];

export interface ConsoleState {
  /** Whether the stream is up; the panels keep showing the last snapshot while it is not. */
  connected: boolean;
  status: Status | null;
  fixtures: FixturePreview[];
  log: LogLine[];
}

/**
 * The live view of the program: one WebSocket to /ws, reconnecting with
 * backoff. On reconnect the log resumes from the last line seen, so nothing
 * is shown twice.
 */
export function useConsole(): ConsoleState {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [fixtures, setFixtures] = useState<FixturePreview[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const nextSeq = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let unmounted = false;

    const connect = () => {
      socket = new WebSocket(streamUrl(nextSeq.current));
      socket.onopen = () => {
        attempts = 0;
        setConnected(true);
      };
      socket.onmessage = (event: MessageEvent<string>) => {
        const message = JSON.parse(event.data) as StreamMessage;
        switch (message.type) {
          case "status":
            setStatus(message.status);
            break;
          case "fixtures":
            setFixtures(message.fixtures);
            break;
          case "log": {
            const last = message.lines.at(-1);
            if (last) {
              nextSeq.current = last.seq + 1;
            }
            setLog((previous) =>
              [...previous, ...message.lines].slice(-LOG_LIMIT),
            );
            break;
          }
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        setConnected(false);
        if (unmounted) {
          return;
        }
        const delay = RECONNECT_MS[Math.min(attempts, RECONNECT_MS.length - 1)];
        attempts += 1;
        timer = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      unmounted = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { connected, status, fixtures, log };
}
