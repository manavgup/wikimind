import { useEffect, useRef } from "react";

interface GraphNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  label: string;
  radius: number;
}

interface GraphEdge {
  from: number;
  to: number;
}

const NODE_LABELS = [
  "Attention",
  "Transformer",
  "BERT",
  "GPT",
  "Embedding",
  "Self-Attention",
  "Tokenizer",
  "Fine-tuning",
  "Loss",
  "Gradient",
  "Backprop",
  "ReLU",
];

const EDGES: GraphEdge[] = [
  { from: 0, to: 1 },
  { from: 0, to: 5 },
  { from: 1, to: 2 },
  { from: 1, to: 3 },
  { from: 1, to: 4 },
  { from: 2, to: 7 },
  { from: 3, to: 7 },
  { from: 4, to: 6 },
  { from: 7, to: 8 },
  { from: 8, to: 9 },
  { from: 9, to: 10 },
  { from: 10, to: 11 },
  { from: 5, to: 4 },
  { from: 3, to: 6 },
];

function KnowledgeGraphCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const nodesRef = useRef<GraphNode[]>([]);
  const frameRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    // Initialize nodes in a rough circle
    if (nodesRef.current.length === 0) {
      nodesRef.current = NODE_LABELS.map((label, i) => {
        const angle = (i / NODE_LABELS.length) * Math.PI * 2;
        const r = Math.min(w, h) * 0.3;
        return {
          x: w / 2 + Math.cos(angle) * r + (Math.random() - 0.5) * 40,
          y: h / 2 + Math.sin(angle) * r + (Math.random() - 0.5) * 40,
          vx: (Math.random() - 0.5) * 0.3,
          vy: (Math.random() - 0.5) * 0.3,
          label,
          radius: 4 + Math.random() * 2,
        };
      });
    }

    const nodes = nodesRef.current;

    function animate() {
      if (!ctx) return;
      ctx.clearRect(0, 0, w, h);

      // Gentle drift
      for (const node of nodes) {
        node.x += node.vx;
        node.y += node.vy;

        // Bounce off edges
        if (node.x < 30 || node.x > w - 30) node.vx *= -1;
        if (node.y < 20 || node.y > h - 20) node.vy *= -1;

        // Keep in bounds
        node.x = Math.max(30, Math.min(w - 30, node.x));
        node.y = Math.max(20, Math.min(h - 20, node.y));
      }

      // Draw edges
      for (const edge of EDGES) {
        const a = nodes[edge.from];
        const b = nodes[edge.to];
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = "rgba(70, 115, 173, 0.15)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Draw nodes
      for (const node of nodes) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(70, 115, 173, 0.6)";
        ctx.fill();

        ctx.font = "10px 'JetBrains Mono', monospace";
        ctx.fillStyle = "rgba(161, 161, 170, 0.7)";
        ctx.textAlign = "center";
        ctx.fillText(node.label, node.x, node.y + node.radius + 12);
      }

      frameRef.current = requestAnimationFrame(animate);
    }

    frameRef.current = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frameRef.current);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="h-full w-full"
      style={{ width: "100%", height: "100%" }}
    />
  );
}

const LINEAGE = [
  { year: "1945", name: "Memex", detail: "Vannevar Bush" },
  { year: "1963", name: "Hypertext", detail: "Ted Nelson" },
  { year: "1995", name: "Wiki", detail: "Ward Cunningham" },
  { year: "2024", name: "WikiMind", detail: "LLM-compiled" },
];

export function MemexSection() {
  return (
    <section className="border-t border-zinc-900 bg-zinc-900/40 px-4 py-20 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="mb-4 text-center text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Lineage
        </div>
        <h2 className="mb-4 text-center text-2xl font-bold text-zinc-100 sm:text-3xl">
          From Memex to WikiMind
        </h2>
        <p className="mx-auto mb-12 max-w-2xl text-center text-sm leading-relaxed text-zinc-400">
          In 1945, Vannevar Bush imagined the Memex &mdash; a device for storing and
          cross-referencing all human knowledge. Eight decades later, the LLM compiler
          makes that vision real: ingest anything, link everything, retrieve instantly.
        </p>

        {/* Timeline */}
        <div className="mb-12 flex flex-wrap items-center justify-center gap-4">
          {LINEAGE.map((item, i) => (
            <div key={item.year} className="flex items-center gap-4">
              <div className="text-center">
                <div className="font-mono text-xs text-zinc-500">{item.year}</div>
                <div className="text-sm font-semibold text-zinc-300">{item.name}</div>
                <div className="text-xs text-zinc-500">{item.detail}</div>
              </div>
              {i < LINEAGE.length - 1 && (
                <svg
                  className="h-4 w-4 text-zinc-700"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="m8.25 4.5 7.5 7.5-7.5 7.5"
                  />
                </svg>
              )}
            </div>
          ))}
        </div>

        {/* Knowledge graph canvas */}
        <div className="mx-auto h-64 max-w-2xl overflow-hidden rounded-xl border border-zinc-800 bg-zinc-950/80 sm:h-72">
          <KnowledgeGraphCanvas />
        </div>
      </div>
    </section>
  );
}
