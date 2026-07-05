import { useEffect, useRef, useState } from "react";

export default function useLiveKpiSnapshot(wsUrl) {
  const [snapshot, setSnapshot] = useState(null);
  const [status, setStatus] = useState("connecting"); // connecting|open|closed|error
  const wsRef = useRef(null);

  useEffect(() => {
    let closedByCleanup = false;

    function connect() {
      setStatus("connecting");
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setStatus("open");

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg?.type === "kpi_snapshot") setSnapshot(msg.data);
        } catch (e) {
          // ignore
        }
      };

      ws.onerror = () => setStatus("error");

      ws.onclose = () => {
        setStatus("closed");
        if (!closedByCleanup) {
          // simple reconnect
          setTimeout(connect, 800);
        }
      };
    }

    connect();

    return () => {
      closedByCleanup = true;
      try {
        wsRef.current?.close();
      } catch {}
    };
  }, [wsUrl]);

  return { snapshot, status };
}
