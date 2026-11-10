"use client";

import { useEffect, useRef } from "react";
import { LAND_COLS, LAND_LAT_MAX, LAND_ROWS, LAND_STEP_DEG } from "@/lib/landMask";
import { isMotionPaused, onMotionChange } from "@/lib/motion";

/**
 * Animated world-shipping backdrop: a dotted world map, BerthIQ's tracked ports as
 * glowing markers, and light pulses travelling along real trade lanes between them
 * (via Malacca, Suez, Gibraltar, the English Channel, Hormuz and Panama).
 *
 * Canvas 2D, no dependencies. The map dots are drawn once to an offscreen layer;
 * each frame only redraws the routes and port markers. Screen-blended over the
 * port photo, so black is transparent.
 * - prefers-reduced-motion, or the header pause button → one still frame.
 * - Pauses while the tab is hidden; slight parallax follows the pointer.
 */

type LatLng = [number, number];

// Real port locations (terminal areas), matching the ports tracked by the backend.
const PORTS: { id: string; name: string; at: LatLng; live: boolean }[] = [
  { id: "rotterdam", name: "Rotterdam", at: [51.95, 4.05], live: true },
  { id: "antwerp", name: "Antwerp", at: [51.27, 4.33], live: true },
  { id: "felixstowe", name: "Felixstowe", at: [51.95, 1.31], live: true },
  { id: "le_havre", name: "Le Havre", at: [49.47, 0.13], live: true },
  { id: "valencia", name: "Valencia", at: [39.44, -0.32], live: true },
  { id: "singapore", name: "Singapore", at: [1.26, 103.82], live: true },
  { id: "hong_kong", name: "Hong Kong", at: [22.34, 114.11], live: true },
  { id: "los_angeles", name: "Los Angeles", at: [33.74, -118.25], live: true },
  { id: "new_york_nj", name: "New York", at: [40.68, -74.1], live: true },
  { id: "jebel_ali", name: "Jebel Ali", at: [25.01, 55.06], live: false },
];

// Shared sea-lane waypoints (lat, lng). Longitudes east of 180° are "unwrapped"
// (e.g. 190 = 170°W) so trans-Pacific lanes stay continuous; they're drawn wrapped.
const W = {
  malacca: [5.9, 95.0],
  sriLanka: [6.0, 80.5],
  babElMandeb: [12.6, 43.4],
  redSea: [20.0, 38.5],
  suez: [29.9, 32.6],
  eastMed: [33.5, 25.0],
  sicily: [37.0, 11.5],
  gibraltar: [36.0, -5.6],
  finisterre: [43.5, -9.8],
  ushant: [48.5, -5.5],
  channel: [50.0, -1.0],
  southChinaSea: [10.0, 110.0],
  hormuz: [26.4, 56.6],
  arabianSea: [20.0, 62.0],
  panama: [8.5, -79.5],
} satisfies Record<string, LatLng>;

function at(id: string): LatLng {
  const port = PORTS.find((p) => p.id === id);
  if (!port) throw new Error(`Unknown port ${id}`);
  return port.at;
}

const SUEZ_WEST: LatLng[] = [W.malacca, W.sriLanka, W.babElMandeb, W.redSea, W.suez, W.eastMed, W.sicily];

const ROUTES: LatLng[][] = [
  // Asia → North Europe via Suez
  [at("singapore"), ...SUEZ_WEST, W.gibraltar, W.finisterre, W.ushant, W.channel, at("rotterdam")],
  // Asia → Mediterranean
  [at("hong_kong"), W.southChinaSea, at("singapore"), ...SUEZ_WEST, [38.5, 2.5], at("valencia")],
  // Trans-Pacific
  [at("hong_kong"), [25.0, 125.0], [35.0, 150.0], [40.0, 190.0], [36.0, 225.0], [at("los_angeles")[0], at("los_angeles")[1] + 360]],
  // Trans-Atlantic
  [at("antwerp"), [51.3, 2.0], W.channel, [49.5, -6.0], [45.0, -35.0], [40.5, -69.0], at("new_york_nj")],
  [at("felixstowe"), [51.0, 1.6], [50.3, -2.5], [48.0, -12.0], [42.0, -45.0], [40.4, -71.0], at("new_york_nj")],
  // Gulf → Asia
  [at("jebel_ali"), W.hormuz, W.arabianSea, [8.0, 77.0], W.sriLanka, W.malacca, at("singapore")],
  // Intra-Europe
  [at("le_havre"), [49.9, -1.5], W.ushant, W.finisterre, W.gibraltar, [37.5, 0.5], at("valencia")],
  // US West → East coast via Panama
  [at("los_angeles"), [20.0, -108.0], W.panama, [15.0, -76.0], [26.0, -74.5], [34.0, -73.5], at("new_york_nj")],
];

const LAT_MIN = LAND_LAT_MAX - LAND_ROWS.length * LAND_STEP_DEG;
const MAX_DPR = 1.5;
const AMBER = "232, 163, 61";
const TEAL = "79, 190, 210";
const LAND = "205, 220, 235";

/** Chaikin corner-cutting, then densify — gives smooth, evenly sampled lanes. */
function smooth(points: LatLng[], iterations = 3, samplesPerSeg = 6): LatLng[] {
  let pts = points;
  for (let k = 0; k < iterations; k++) {
    const out: LatLng[] = [pts[0]!];
    for (let i = 0; i < pts.length - 1; i++) {
      const [a0, a1] = pts[i]!;
      const [b0, b1] = pts[i + 1]!;
      out.push([0.75 * a0 + 0.25 * b0, 0.75 * a1 + 0.25 * b1], [0.25 * a0 + 0.75 * b0, 0.25 * a1 + 0.75 * b1]);
    }
    out.push(pts[pts.length - 1]!);
    pts = out;
  }
  const dense: LatLng[] = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const [a0, a1] = pts[i]!;
    const [b0, b1] = pts[i + 1]!;
    for (let s = 0; s < samplesPerSeg; s++) {
      const t = s / samplesPerSeg;
      dense.push([a0 + (b0 - a0) * t, a1 + (b1 - a1) * t]);
    }
  }
  dense.push(pts[pts.length - 1]!);
  return dense;
}

const SMOOTH_ROUTES = ROUTES.map((r) => smooth(r));

export function ShippingRoutes({ opacity = 0.9 }: { opacity?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let still = reduceMotion || isMotionPaused();
    const dotsLayer = document.createElement("canvas");
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 };

    // Map frame: full-width equirectangular, centred slightly above middle.
    let dpr = 1;
    let mapW = 0;
    let mapH = 0;
    let offX = 0;
    let offY = 0;
    let routesPx: { pts: [number, number][]; cum: number[]; len: number }[] = [];

    const project = ([lat, lng]: LatLng): [number, number] => [
      offX + ((lng + 180) / 360) * mapW,
      offY + ((LAND_LAT_MAX - lat) / (LAND_LAT_MAX - LAT_MIN)) * mapH,
    ];

    function layout() {
      dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas!.width = Math.floor(w * dpr);
      canvas!.height = Math.floor(h * dpr);
      // Fill the width (slightly over-scanned), keep the map's true aspect ratio.
      mapW = w * 1.08;
      mapH = mapW * ((LAND_LAT_MAX - LAT_MIN) / 360);
      offX = (w - mapW) / 2;
      offY = Math.max(h * 0.12, (h - mapH) * 0.45);

      // Static dotted continents, drawn once per resize.
      dotsLayer.width = canvas!.width;
      dotsLayer.height = canvas!.height;
      const d = dotsLayer.getContext("2d")!;
      d.setTransform(dpr, 0, 0, dpr, 0, 0);
      const cell = mapW / LAND_COLS;
      const r = Math.max(0.9, cell * 0.22);
      d.fillStyle = `rgba(${LAND}, 0.30)`;
      LAND_ROWS.forEach((row, ri) => {
        const lat = LAND_LAT_MAX - (ri + 0.5) * LAND_STEP_DEG;
        let col = 0;
        let land = false;
        for (const run of row.split(".")) {
          const n = Number(run);
          if (land) {
            for (let c = col; c < col + n; c++) {
              const [x, y] = project([lat, -180 + (c + 0.5) * LAND_STEP_DEG]);
              d.beginPath();
              d.arc(x, y, r, 0, Math.PI * 2);
              d.fill();
            }
          }
          col += n;
          land = !land;
        }
      });

      // Route geometry in pixels, with cumulative length for pulse placement.
      routesPx = SMOOTH_ROUTES.map((route) => {
        const pts = route.map(project);
        const cum = [0];
        for (let i = 1; i < pts.length; i++) {
          cum.push(cum[i - 1]! + Math.hypot(pts[i]![0] - pts[i - 1]![0], pts[i]![1] - pts[i - 1]![1]));
        }
        return { pts, cum, len: cum[cum.length - 1]! };
      });
    }

    // Draw a route (or a slice of it), repeated one map-width left so trans-Pacific lanes wrap.
    function strokePath(pts: [number, number][], from: number, to: number) {
      for (const shift of [0, -mapW]) {
        ctx!.beginPath();
        for (let i = from; i <= to; i++) {
          const [x, y] = pts[i]!;
          if (i === from) ctx!.moveTo(x + shift, y);
          else ctx!.lineTo(x + shift, y);
        }
        ctx!.stroke();
      }
    }

    function indexAt(route: { cum: number[] }, dist: number) {
      let i = 0;
      while (i < route.cum.length - 1 && route.cum[i + 1]! < dist) i++;
      return i;
    }

    function draw(time: number) {
      // A zero-size window (e.g. a tab loaded in the background) leaves a zero-size
      // layer, and drawImage throws on it, which would kill the loop for good. Skip
      // the frame instead; the next resize gives the layer a real size.
      if (dotsLayer.width === 0 || dotsLayer.height === 0) return;
      const t = time / 1000;
      pointer.x += (pointer.tx - pointer.x) * 0.05;
      pointer.y += (pointer.ty - pointer.y) * 0.05;

      ctx!.setTransform(1, 0, 0, 1, 0, 0);
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      ctx!.drawImage(dotsLayer, pointer.x * dpr, pointer.y * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, pointer.x * dpr, pointer.y * dpr);
      ctx!.lineCap = "round";
      ctx!.lineJoin = "round";

      routesPx.forEach((route, ri) => {
        // Faint lane
        ctx!.strokeStyle = `rgba(${TEAL}, 0.28)`;
        ctx!.lineWidth = 1;
        strokePath(route.pts, 0, route.pts.length - 1);

        // Two pulses per lane, each a short comet with a fading tail.
        for (let k = 0; k < 2; k++) {
          const speed = 70 + (ri % 3) * 18; // px per second
          const head = ((t * speed + k * route.len * 0.5 + ri * 137) % (route.len + 160)) - 40;
          const tail = 90;
          const segments = 6;
          for (let s = 0; s < segments; s++) {
            const a = head - (tail * (s + 1)) / segments;
            const b = head - (tail * s) / segments;
            if (b < 0 || a > route.len) continue;
            const i0 = indexAt(route, Math.max(0, a));
            const i1 = indexAt(route, Math.min(route.len, b)) + 1;
            const alpha = (1 - s / segments) * 0.85;
            ctx!.strokeStyle = s < 2 ? `rgba(${AMBER}, ${alpha})` : `rgba(${TEAL}, ${alpha * 0.8})`;
            ctx!.lineWidth = 2.2 - s * 0.25;
            strokePath(route.pts, i0, Math.min(i1, route.pts.length - 1));
          }
        }
      });

      // Port markers: a steady core plus an expanding ring.
      for (const [i, port] of PORTS.entries()) {
        const [x, y] = project(port.at);
        const color = port.live ? AMBER : "150, 150, 150";
        const phase = (t * 0.6 + i * 0.13) % 1;
        if (!still) {
          ctx!.beginPath();
          ctx!.arc(x, y, 3 + phase * 14, 0, Math.PI * 2);
          ctx!.strokeStyle = `rgba(${color}, ${0.5 * (1 - phase)})`;
          ctx!.lineWidth = 1.2;
          ctx!.stroke();
        }
        const glow = ctx!.createRadialGradient(x, y, 0, x, y, 9);
        glow.addColorStop(0, `rgba(${color}, 0.9)`);
        glow.addColorStop(1, `rgba(${color}, 0)`);
        ctx!.fillStyle = glow;
        ctx!.beginPath();
        ctx!.arc(x, y, 9, 0, Math.PI * 2);
        ctx!.fill();
        ctx!.fillStyle = `rgba(255, 240, 220, 0.95)`;
        ctx!.beginPath();
        ctx!.arc(x, y, 1.8, 0, Math.PI * 2);
        ctx!.fill();
      }
    }

    let frame = 0;
    function loop(now: number) {
      draw(now);
      frame = requestAnimationFrame(loop);
    }
    function onPointerMove(e: PointerEvent) {
      // Up to ~10px of parallax, opposite to the pointer for depth.
      pointer.tx = -(e.clientX / window.innerWidth - 0.5) * 20;
      pointer.ty = -(e.clientY / window.innerHeight - 0.5) * 12;
    }
    function onVisibility() {
      cancelAnimationFrame(frame);
      if (!document.hidden && !still) frame = requestAnimationFrame(loop);
    }
    function onResize() {
      layout();
      if (still) draw(8000);
    }
    function applyMotion() {
      cancelAnimationFrame(frame);
      if (still) draw(8000);
      else frame = requestAnimationFrame(loop);
    }

    layout();
    applyMotion();
    if (!reduceMotion) {
      window.addEventListener("pointermove", onPointerMove);
      document.addEventListener("visibilitychange", onVisibility);
    }
    window.addEventListener("resize", onResize);
    const stopListening = onMotionChange((paused) => {
      still = reduceMotion || paused;
      applyMotion();
    });

    return () => {
      stopListening();
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="absolute inset-0 h-full w-full"
      style={{
        opacity,
        mixBlendMode: "screen",
        // Soften the edges so the map frames the content instead of boxing it in.
        maskImage: "radial-gradient(ellipse 75% 70% at 50% 50%, black 55%, transparent 100%)",
        WebkitMaskImage: "radial-gradient(ellipse 75% 70% at 50% 50%, black 55%, transparent 100%)",
      }}
    />
  );
}
