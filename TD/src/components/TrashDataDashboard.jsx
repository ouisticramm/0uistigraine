import React, { useState, useEffect, useRef, useCallback, useReducer } from "react";
import useLiveKpiSnapshot from "../hooks.useLiveKpiSnapshot";

const MATERIALS = [
  { code: "PET", label: "PET", color: "#38f779", density: 1.38, baseShare: 0.27 },
  { code: "PEHD", label: "PEHD", color: "#38f779", density: 0.96, baseShare: 0.17 },
  { code: "ALU", label: "Aluminium", color: "#38f779", density: 2.7, baseShare: 0.07 },
  { code: "ACIER", label: "Acier", color: "#38f779", density: 7.8, baseShare: 0.06 },
  { code: "CARTON", label: "Carton", color: "#38f779", density: 0.7, baseShare: 0.24 },
  { code: "NONREC", label: "Non recyclables", color: "#9aa7a1", density: 1.0, baseShare: 0.04, muted: true },
  { code: "ENERGIE", label: "Valorisables énergie", color: "#50d7d2", density: 1.0, baseShare: 0.15, energy: true },
];

const BRANDS = [
  { name: "Coca-Cola", material: "ALU", note: "Canettes et bouteilles majoritairement en flux valorisable" },
  { name: "Cristaline", material: "PET", note: "PET clair, fort potentiel de captation" },
  { name: "Evian", material: "PET", note: "PET clair, taux de refus à surveiller" },
  { name: "Volvic", material: "PET", note: "PET clair, régularité élevée sur A3" },
  { name: "Red Bull", material: "ALU", note: "Aluminium, marge matière prioritaire" },
  { name: "NovaDrink", material: "PET", note: "Forte cadence, qualité stable" },
  { name: "FreshBox", material: "CARTON", note: "Carton, taux d'humidité à surveiller" },
];

const BASE_PRICES = { PET: 575, PEHD: 710, ALU: 1180, CARTON: 145, ACIER: 260, ENERGIE: 60, NONREC: 0 };

const ALERT_TEMPLATES = [
  { type: "high", icon: "!", title: "Erreur de tri détectée", make: () => `Acier détecté dans flux PET, caméra C${1 + Math.floor(Math.random() * 4)}.` },
  { type: "medium", icon: "↘", title: "Chute de qualité matière", make: () => `Pureté PEHD passée sous ${88 + Math.floor(Math.random() * 4)}% sur les 20 dernières minutes.` },
  { type: "sale", icon: "€", title: "Opportunité de vente", make: (ctx) => `Cours ${ctx.material} favorable, marge estimée +${ctx.amount} €.` },
  { type: "pickup", icon: "▰", title: "Enlèvement à programmer", make: () => `Balle ${["PET", "carton", "aluminium"][Math.floor(Math.random() * 3)]} complète prévue dans ${10 + Math.floor(Math.random() * 50)} min.` },
];

function rand(min, max) { return min + Math.random() * (max - min); }
function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function fmtEUR(n) { return n.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) + " €"; }
function fmtT(n) { return n.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " t"; }

function useTrashDataSimulator() {
  const [running, setRunning] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [, forceRerender] = useReducer((x) => x + 1, 0);

  const stateRef = useRef({
    startedAt: Date.now(),
    totalsByMaterial: Object.fromEntries(MATERIALS.map((m) => [m.code, 18 + Math.random() * 10])),
    detectionsCount: 482940,
    errorRatePct: 3.8,
    purityPct: 94.2,
    brandCounts: Object.fromEntries(BRANDS.map((b) => [b.name, Math.floor(rand(6000, 25000))])),
    prices: { ...BASE_PRICES },
    priceDrift: Object.fromEntries(Object.keys(BASE_PRICES).map((k) => [k, 0])),
    history: Array.from({ length: 12 }, (_, i) => ({
      t: i,
      throughput: 12 + Math.random() * 8,
    })),
    alerts: [
      { id: "seed-1", type: "high", icon: "!", title: "Erreur de tri détectée", message: "Acier détecté dans flux PET, caméra C2, 14:32.", ts: Date.now() - 60000 },
      { id: "seed-2", type: "medium", icon: "↘", title: "Chute de qualité matière", message: "Pureté PEHD passée sous 90% sur les 20 dernières minutes.", ts: Date.now() - 120000 },
    ],
    lastDetection: null,
    baleProgress: 76,
  });

  const snapshotRef = useRef(null);

  const step = useCallback(() => {
    const s = stateRef.current;

    const mat = pick(MATERIALS.filter((m) => Math.random() < m.baseShare + 0.05));
    const chosenMat = mat || pick(MATERIALS);
    const weight = rand(0.01, 0.4);
    s.totalsByMaterial[chosenMat.code] += weight;
    s.detectionsCount += 1;

    const matchingBrands = BRANDS.filter((b) => b.material === chosenMat.code);
    const brandPool = matchingBrands.length > 0 ? matchingBrands : BRANDS;
    const brand = Math.random() < 0.55 ? pick(brandPool) : null;
    if (brand && s.brandCounts[brand.name] !== undefined) {
      s.brandCounts[brand.name] += 1;
    }

    s.lastDetection = {
      material: chosenMat.label,
      code: chosenMat.code,
      weight,
      brand: brand ? brand.name : null,
      confidence: 90 + Math.random() * 9.5,
      ts: Date.now(),
    };

    s.errorRatePct = Math.max(1.2, Math.min(7, s.errorRatePct + rand(-0.15, 0.13)));
    s.purityPct = Math.max(85, Math.min(98, s.purityPct + rand(-0.12, 0.14)));

    Object.keys(s.prices).forEach((k) => {
      if (k === "NONREC") return;
      s.priceDrift[k] = Math.max(-0.12, Math.min(0.12, s.priceDrift[k] + rand(-0.01, 0.01)));
      s.prices[k] = Math.max(10, BASE_PRICES[k] * (1 + s.priceDrift[k]));
    });

    if (s.detectionsCount % 8 === 0) {
      s.history.push({ t: s.history[s.history.length - 1].t + 1, throughput: Math.max(8, Math.min(24, s.history[s.history.length - 1].throughput + rand(-1.2, 1.4))) });
      if (s.history.length > 14) s.history.shift();
    }

    s.baleProgress += rand(0.3, 1.1);
    if (s.baleProgress >= 100) s.baleProgress = 4;

    if (Math.random() < 0.045) {
      const tpl = pick(ALERT_TEMPLATES);
      const ctx = { material: chosenMat.label, amount: Math.floor(rand(400, 2400)) };
      s.alerts = [
        { id: `a-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, type: tpl.type, icon: tpl.icon, title: tpl.title, message: tpl.make(ctx), ts: Date.now() },
        ...s.alerts,
      ].slice(0, 6);
    }

    snapshotRef.current = buildSnapshot(s);
    forceRerender();
  }, []);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(step, 1400 / speed);
    return () => clearInterval(id);
  }, [running, speed, step]);

  if (!snapshotRef.current) snapshotRef.current = buildSnapshot(stateRef.current);

  return { snapshot: snapshotRef.current, running, setRunning, speed, setSpeed};
}

function buildSnapshot(s) {
  const totalT = Object.values(s.totalsByMaterial).reduce((a, b) => a + b, 0);
  const recyclables = MATERIALS.filter((m) => !m.muted && !m.energy);
  const valueByMaterial = {};
  let totalValue = 0;
  recyclables.concat(MATERIALS.filter((m) => m.energy)).forEach((m) => {
    const tonnes = s.totalsByMaterial[m.code];
    const price = s.prices[m.code] ?? 0;
    const value = tonnes * price;
    valueByMaterial[m.code] = value;
    totalValue += value;
  });

  const qualityScore = Math.round(s.purityPct);
  const performanceScore = Math.round(Math.max(0, Math.min(100, 100 - s.errorRatePct * 6)));
  const refusalLoss = totalValue * 0.07;
  const valorisationScore = Math.round(Math.max(0, Math.min(100, 100 - (refusalLoss / Math.max(totalValue, 1)) * 220)));
  const globalScore = Math.round(qualityScore * 0.4 + performanceScore * 0.3 + valorisationScore * 0.3);

  const topBrands = Object.entries(s.brandCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, count]) => ({ name, count, note: BRANDS.find((b) => b.name === name)?.note || "" }));

  const opportunities = [
    { label: "Refus valorisables", value: Math.round(refusalLoss), note: "Récupérables dans les refus" },
    { label: "Opportunité aluminium", value: Math.round((s.prices.ALU - BASE_PRICES.ALU) > 0 ? Math.abs(s.prices.ALU - BASE_PRICES.ALU) * (s.totalsByMaterial.ALU * 0.4) : rand(800, 1900)), note: "Cours favorable et stock disponible" },
    { label: "Qualité PET", value: Math.round(rand(1500, 2800)), note: "Gain potentiel sur pureté PET clair" },
  ];
  const opportunityTotal = opportunities.reduce((a, o) => a + o.value, 0);

  return {
    totalT,
    totalValue,
    valueByMaterial,
    detectionsCount: s.detectionsCount,
    errorRatePct: s.errorRatePct,
    purityPct: s.purityPct,
    prices: s.prices,
    priceDrift: s.priceDrift,
    history: s.history,
    alerts: s.alerts,
    lastDetection: s.lastDetection,
    baleProgress: s.baleProgress,
    score: { global: globalScore, quality: qualityScore, performance: performanceScore, valorisation: valorisationScore },
    topBrands,
    opportunities,
    opportunityTotal,
    tonnagePerHour: Math.max(8, Math.min(26, (s.history[s.history.length - 1]?.throughput) || 16)),
  };
}

function Bar({ pct, tone = "green" }) {
  const colors = {
    green: "linear-gradient(90deg,#0a8f49,#38f779)",
    muted: "linear-gradient(90deg,#515b57,#9aa7a1)",
    energy: "linear-gradient(90deg,#008c7d,#50d7d2)",
  };
  return (
    <div style={{ height: 10, background: "rgba(255,255,255,.07)", overflow: "hidden", borderRadius: 2 }}>
      <div style={{ width: `${Math.max(2, Math.min(100, pct))}%`, height: "100%", background: colors[tone], transition: "width .6s ease" }} />
    </div>
  );
}

function Panel({ title, eyebrow, right, span, children }) {
  return (
    <article
      className="panel"
      style={{
        gridColumn: `span ${span || 12}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 18 }}>
        <div>
          <p style={{ margin: "0 0 6px", textTransform: "uppercase", fontSize: 11, fontWeight: 700, letterSpacing: ".12em", color: "#8ea09a" }}>{eyebrow}</p>
          <h2 style={{ margin: 0, fontSize: 18, color: "#eef8f0" }}>{title}</h2>
        </div>
        {right}
      </div>
      {children}
    </article>
  );
}

function Chip({ children, tone = "neutral" }) {
  const toneClass = tone === "live" ? "chip--live" : tone === "danger" ? "chip--danger" : "";
  return <span className={`chip ${toneClass}`}>{children}</span>;
}

function KpiCard({ label, value, sub, accent, warning }) {
  const cls = `kpi ${accent ? "kpi--accent" : ""} ${warning ? "kpi--warning" : ""}`.trim();
  return (
    <article className={cls} style={{ position: "relative", overflow: "hidden" }}>
      <p style={{ margin: "0 0 7px", fontSize: 13, color: "#8ea09a" }}>{label}</p>
      <strong style={{ display: "block", fontSize: 25, lineHeight: 1.1, color: "#eef8f0" }}>{value}</strong>
      <small style={{ display: "block", marginTop: 10, fontSize: 12, color: "#8ea09a" }}>{sub}</small>
    </article>
  );
}

function ThroughputChart({ history }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * ratio;
    canvas.height = 200 * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, rect.width, 200);
    const padding = 24, width = rect.width - padding * 2, height = 140, top = 16, max = 26;
    ctx.strokeStyle = "rgba(255,255,255,0.07)";
    ctx.lineWidth = 1;
    for (let i = 0; i < 4; i++) {
      const y = top + (height / 3) * i;
      ctx.beginPath();
      ctx.moveTo(padding, y);
      ctx.lineTo(rect.width - padding, y);
      ctx.stroke();
    }
    const pts = history.map((h, i) => ({
      x: padding + (width / Math.max(1, history.length - 1)) * i,
      y: top + height - (h.throughput / max) * height,
    }));
    const gradient = ctx.createLinearGradient(0, top, 0, top + height);
    gradient.addColorStop(0, "rgba(56,247,121,0.42)");
    gradient.addColorStop(1, "rgba(56,247,121,0)");
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.lineTo(pts[pts.length - 1].x, top + height);
    ctx.lineTo(pts[0].x, top + height);
    ctx.closePath();
    ctx.fillStyle = gradient;
    ctx.fill();
    ctx.beginPath();
    pts.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = "#38f779";
    ctx.lineWidth = 3;
    ctx.stroke();
    const last = pts[pts.length - 1];
    if (last) {
      ctx.fillStyle = "#06120b";
      ctx.beginPath();
      ctx.arc(last.x, last.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#38f779";
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }, [history]);
  return <canvas ref={ref} style={{ width: "100%", maxWidth: "100%", height: 200 }} aria-label="Tendance débit conveyor" />;
}

function PurityRing({ value }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas.getContext("2d");
    const center = 90, radius = 72;
    ctx.clearRect(0, 0, 180, 180);
    ctx.lineWidth = 13;
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.beginPath();
    ctx.arc(center, center, radius, -Math.PI / 2, Math.PI * 1.5);
    ctx.stroke();
    ctx.strokeStyle = "#38f779";
    ctx.beginPath();
    ctx.arc(center, center, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (value / 100));
    ctx.stroke();
  }, [value]);
  return (
    <div style={{ position: "relative", display: "grid", justifyItems: "center" }}>
      <canvas ref={ref} width={180} height={180} aria-label="Pureté estimée" />
      <strong style={{ position: "absolute", top: 70, fontSize: 28, color: "#eef8f0" }}>{value.toFixed(1)}%</strong>
      <span style={{ marginTop: 8, color: "#8ea09a", fontSize: 12 }}>Pureté estimée</span>
    </div>
  );
}

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `il y a ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `il y a ${m} min`;
  return `il y a ${Math.floor(m / 60)} h`;
}

export default function TrashDataDashboard() {
  const { snapshot: snap, status: wsStatus } = useLiveKpiSnapshot("ws://localhost:8000/ws/live");

  if (!snap) {
    return (
      <div className="app">
        <div className="dashboard">
          <p className="muted" style={{ fontSize: 13 }}>Connexion WebSocket… ({wsStatus})</p>
        </div>
      </div>
    );
  }

  const matSummary = MATERIALS.map((m) => {
    const value = snap.valueByMaterial[m.code] || 0;
    const price = snap.prices[m.code] || 0;
    const tonnes = price > 0 ? value / price : value;
    return { ...m, tonnes };
  });
  const maxTonnes = Math.max(...matSummary.map((m) => m.tonnes), 1);

  return (
    <div className="app">
      <div className="dashboard">
      <header style={{ display: "flex", justifyContent: "space-between", gap: 18, alignItems: "center", marginBottom: 20, flexWrap: "wrap" }}>
        <div>
          <p style={{ margin: "0 0 6px", textTransform: "uppercase", fontSize: 11, fontWeight: 700, letterSpacing: ".12em", color: "#8ea09a" }}>
            Centre de tri · Ligne Convoyeur A3 · Démo simulée
          </p>
          <h1 style={{ margin: 0, fontSize: 30, color: "#eef8f0" }}>Tableau de bord opérationnel</h1>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, color: "#8ea09a" }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#38f779", boxShadow: "0 0 0 6px rgba(56,247,121,.12)" }} />
            WebSocket {wsStatus} · {snap.detectionsCount.toLocaleString("fr-FR")} détections
          </span>
        </div>
      </header>

      {snap.lastDetection && (
        <div style={{ marginBottom: 16, fontSize: 12, color: "#8ea09a", display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ color: "#38f779" }}>● dernière détection</span>
          {snap.lastDetection.material} · {snap.lastDetection.weight.toFixed(2)} kg · confiance {snap.lastDetection.confidence.toFixed(1)}%
          {snap.lastDetection.brand ? ` · marque ${snap.lastDetection.brand}` : ""}
        </div>
      )}

      <section className="grid grid-6" style={{ marginBottom: 14 }}>
        <KpiCard accent label="Tonnage heure" value={`${snap.tonnagePerHour.toFixed(1)} t/h`} sub="flux temps réel" />
        <KpiCard label="Total analysé" value={fmtT(snap.totalT)} sub="depuis le début de session" />
        <KpiCard label="Valeur matières" value={fmtEUR(snap.totalValue)} sub="stock estimé en temps réel" />
        <KpiCard label="Emballages détectés" value={snap.detectionsCount.toLocaleString("fr-FR")} sub="confiance IA simulée ~96%" />
        <KpiCard warning label="Erreurs de tri" value={`${snap.errorRatePct.toFixed(1)}%`} sub="objectif < 3%" />
        <KpiCard label="Pureté des balles" value={`${snap.purityPct.toFixed(1)}%`} sub="objectif 95%" />
      </section>

      <section className="grid grid-12">
        <div style={{ gridColumn: "span 7" }}>
          <Panel eyebrow="Vision IA (simulée)" title="Analyse des matières" right={<Chip tone="live">Live</Chip>} span={12}>
            <div style={{ display: "grid", gap: 14 }}>
              {matSummary.map((m) => (
                <div key={m.code} style={{ display: "grid", gridTemplateColumns: "170px minmax(120px,1fr) 78px", alignItems: "center", gap: 12 }}>
                  <span style={{ color: m.muted ? "#9aa7a1" : "#eef8f0" }}>{m.label}</span>
                  <Bar pct={(m.tonnes / maxTonnes) * 100} tone={m.muted ? "muted" : m.energy ? "energy" : "green"} />
                  <strong style={{ textAlign: "right" }}>{fmtT(m.tonnes)}</strong>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 5" }}>
          <Panel eyebrow="Flux convoyeur" title="Tendance débit" span={12}>
            <ThroughputChart history={snap.history} />
          </Panel>
        </div>

        <div style={{ gridColumn: "span 7" }}>
          <Panel eyebrow="Détection marques" title="Top marques détectées" right={<Chip>IA vision</Chip>} span={12}>
            <ol style={{ display: "grid", gap: 0, margin: 0, padding: 0, listStyle: "none" }}>
              {snap.topBrands.map((b, i) => (
                <li key={b.name} style={{ display: "grid", gridTemplateColumns: "34px 1fr auto", gap: 12, alignItems: "center", padding: "11px 0", borderBottom: i < snap.topBrands.length - 1 ? "1px solid rgba(255,255,255,.07)" : "none" }}>
                  <span style={{ width: 28, height: 28, display: "grid", placeItems: "center", background: "rgba(56,247,121,.1)", border: "1px solid rgba(56,247,121,.25)", color: "#38f779", fontWeight: 800, fontSize: 12, borderRadius: 3 }}>{i + 1}</span>
                  <div>
                    <strong style={{ display: "block" }}>{b.name}</strong>
                    <span style={{ color: "#8ea09a", fontSize: 12 }}>{b.note}</span>
                  </div>
                  <em style={{ fontStyle: "normal", color: "#d7e8df", fontWeight: 800 }}>{b.count.toLocaleString("fr-FR")}</em>
                </li>
              ))}
            </ol>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 5" }}>
          <Panel eyebrow="Pilotage économique" title="Décision matières" span={12}>
            <div style={{ padding: 16, background: "rgba(56,247,121,.08)", border: "1px solid rgba(56,247,121,.24)", marginBottom: 14, borderRadius: 4 }}>
              <span style={{ color: "#8ea09a", fontSize: 12 }}>Recommandation IA</span>
              <strong style={{ display: "block", margin: "6px 0", fontSize: 22, color: "#38f779" }}>
                {snap.priceDrift.PET > 0.03 ? "Vendre maintenant" : "Conserver le stock"}
              </strong>
              <p style={{ margin: 0, color: "#c9d7d0", lineHeight: 1.45 }}>
                PET clair {snap.priceDrift.PET >= 0 ? "+" : ""}{(snap.priceDrift.PET * 100).toFixed(1)}% vs base. Stock valorisé à {fmtEUR(snap.valueByMaterial.PET || 0)}.
              </p>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 10, marginBottom: 16 }}>
              {["PET", "PEHD", "ALU", "CARTON"].map((k) => (
                <div key={k} style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", padding: 12, borderRadius: 4 }}>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>{k === "ALU" ? "Alu" : k}</span>
                  <strong style={{ display: "block", marginTop: 5 }}>{Math.round(snap.prices[k])} €/t</strong>
                </div>
              ))}
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8, fontSize: 13 }}>
                <span style={{ color: "#8ea09a" }}>Balle PET en cours</span>
                <strong>{Math.round(100 - snap.baleProgress)}% restant</strong>
              </div>
              <div style={{ height: 10, background: "rgba(255,255,255,.07)", overflow: "hidden", borderRadius: 2 }}>
                <div style={{ width: `${snap.baleProgress}%`, height: "100%", background: "linear-gradient(90deg,#0a8f49,#38f779)", transition: "width .6s ease" }} />
              </div>
            </div>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 6" }}>
          <Panel eyebrow="Pilotage global" title="TrashData Score" span={12}>
            <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 20, alignItems: "center" }}>
              <div style={{ position: "relative", width: 162, height: 162, display: "grid", placeItems: "center", margin: "auto", borderRadius: "50%", background: `conic-gradient(#38f779 0 ${snap.score.global}%, rgba(255,255,255,.08) ${snap.score.global}% 100%)` }}>
                <div style={{ position: "absolute", inset: 13, borderRadius: "50%", background: "#09100d", border: "1px solid rgba(255,255,255,.06)" }} />
                <strong style={{ position: "relative", fontSize: 40, color: "#38f779" }}>{snap.score.global}</strong>
                <span style={{ position: "relative", color: "#8ea09a", fontSize: 12, marginTop: -18 }}>/100</span>
              </div>
              <div>
                <div style={{ display: "grid", gap: 10 }}>
                  {[
                    ["Qualité", snap.score.quality],
                    ["Performance", snap.score.performance],
                    ["Valorisation", snap.score.valorisation],
                  ].map(([label, val]) => (
                    <div key={label} style={{ display: "grid", gridTemplateColumns: "105px minmax(80px,1fr) 44px", alignItems: "center", gap: 10 }}>
                      <span style={{ color: "#8ea09a", fontSize: 13 }}>{label}</span>
                      <Bar pct={val} />
                      <strong style={{ textAlign: "right" }}>{val}</strong>
                    </div>
                  ))}
                </div>
                <p style={{ margin: "12px 0 0", lineHeight: 1.45, color: "#8ea09a", fontSize: 13 }}>
                  Score recalculé en continu à partir du flux simulé — qualité (pureté), performance (taux d'erreur), valorisation (pertes en refus).
                </p>
              </div>
            </div>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 6" }}>
          <Panel eyebrow="Leviers économiques" title="Opportunités IA détectées" span={12}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 10 }}>
              {snap.opportunities.map((o) => (
                <div key={o.label} style={{ padding: 14, background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", borderRadius: 4 }}>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>{o.label}</span>
                  <strong style={{ display: "block", fontSize: 22, margin: "7px 0", color: "#f4bf45" }}>{fmtEUR(o.value)}</strong>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>{o.note}</span>
                </div>
              ))}
              <div style={{ padding: 14, background: "rgba(56,247,121,.08)", border: "1px solid rgba(56,247,121,.34)", borderRadius: 4 }}>
                <span style={{ color: "#8ea09a", fontSize: 12 }}>Potentiel total identifié</span>
                <strong style={{ display: "block", fontSize: 22, margin: "7px 0", color: "#38f779" }}>{fmtEUR(snap.opportunityTotal)}</strong>
                <span style={{ color: "#8ea09a", fontSize: 12 }}>Actions priorisées aujourd'hui</span>
              </div>
            </div>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 6" }}>
          <Panel eyebrow="Contrôle qualité" title="Qualité des balles" right={<Chip tone="live">Conforme</Chip>} span={12}>
            <div style={{ display: "grid", gridTemplateColumns: "210px 1fr", gap: 20, alignItems: "center" }}>
              <PurityRing value={snap.purityPct} />
              <div style={{ display: "grid", gap: 10 }}>
                <div style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", padding: 12, borderRadius: 4 }}>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>Taux de contaminants</span>
                  <strong style={{ display: "block", marginTop: 5 }}>{(100 - snap.purityPct).toFixed(1)}%</strong>
                </div>
                <div style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", padding: 12, borderRadius: 4 }}>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>Homogénéité matière</span>
                  <strong style={{ display: "block", marginTop: 5 }}>{(snap.purityPct - rand(1, 3)).toFixed(1)}%</strong>
                </div>
                <div style={{ background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", padding: 12, borderRadius: 4 }}>
                  <span style={{ color: "#8ea09a", fontSize: 12 }}>Statut lot PEHD</span>
                  <strong style={{ display: "block", marginTop: 5, color: "#f4bf45" }}>{snap.purityPct < 92 ? "À surveiller" : "Stable"}</strong>
                </div>
              </div>
            </div>
          </Panel>
        </div>

        <div style={{ gridColumn: "span 12" }}>
          <Panel eyebrow="Alertes IA" title="Événements prioritaires" right={<Chip tone="danger">{snap.alerts.length} actives</Chip>} span={12}>
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(2, minmax(0,1fr))" }}>
              {snap.alerts.map((a) => {
                const toneColor = a.type === "high" ? "#ff6464" : a.type === "medium" ? "#f4bf45" : "#38f779";
                return (
                  <div key={a.id} style={{ display: "grid", gridTemplateColumns: "34px 1fr", gap: 12, padding: 12, background: "rgba(255,255,255,.035)", border: "1px solid rgba(255,255,255,.07)", borderRadius: 4 }}>
                    <span style={{ marginTop: 2, color: toneColor, fontWeight: 800, fontSize: 16 }}>{a.icon}</span>
                    <div>
                      <strong style={{ display: "block", marginBottom: 4 }}>{a.title}</strong>
                      <p style={{ margin: 0, lineHeight: 1.42, color: "#c9d7d0" }}>{a.message}</p>
                      <span style={{ color: "#8ea09a", fontSize: 11 }}>{timeAgo(a.ts)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        </div>
      </section>

      <p style={{ marginTop: 18, fontSize: 11, color: "#5f6a65", textAlign: "center" }}>
        Démo TrashData — données simulées localement. Contrat de données aligné sur le schéma DETECTION / MATERIAL / BALE / ALERT déjà conçu, prêt à être branché sur le backend FastAPI réel.
      </p>
      </div>
    </div>
  );
}
