/**
 * Subtle SVG neural-network / synapse-pulse animation.
 * Pure CSS keyframes — no external animation library.
 */
export default function NeuralAnimation() {
  // Node positions (cx, cy) — a sparse 3-layer network layout
  const nodes = [
    // Layer 1
    { id: "n1", cx: 60, cy: 40 },
    { id: "n2", cx: 60, cy: 80 },
    { id: "n3", cx: 60, cy: 120 },
    // Layer 2
    { id: "n4", cx: 150, cy: 30 },
    { id: "n5", cx: 150, cy: 75 },
    { id: "n6", cx: 150, cy: 120 },
    { id: "n7", cx: 150, cy: 160 },
    // Layer 3
    { id: "n8", cx: 240, cy: 55 },
    { id: "n9", cx: 240, cy: 100 },
    { id: "n10", cx: 240, cy: 145 },
    // Output
    { id: "n11", cx: 320, cy: 70 },
    { id: "n12", cx: 320, cy: 115 },
  ];

  const edges = [
    // L1 → L2
    ["n1", "n4"], ["n1", "n5"],
    ["n2", "n4"], ["n2", "n5"], ["n2", "n6"],
    ["n3", "n5"], ["n3", "n6"], ["n3", "n7"],
    // L2 → L3
    ["n4", "n8"], ["n4", "n9"],
    ["n5", "n8"], ["n5", "n9"], ["n5", "n10"],
    ["n6", "n9"], ["n6", "n10"],
    ["n7", "n9"], ["n7", "n10"],
    // L3 → output
    ["n8", "n11"], ["n8", "n12"],
    ["n9", "n11"], ["n9", "n12"],
    ["n10", "n12"],
  ];

  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));

  // Pulse dots: each travels along a different edge with staggered delay
  const pulses = edges.slice(0, 10).map((edge, i) => ({
    edge,
    delay: `${(i * 0.43).toFixed(2)}s`,
    dur: `${2.2 + (i % 4) * 0.35}s`,
  }));

  return (
    <div className="neural-wrapper" aria-hidden="true">
      <svg
        viewBox="0 0 380 190"
        xmlns="http://www.w3.org/2000/svg"
        className="neural-svg"
        fill="none"
      >
        <defs>
          <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#d97706" stopOpacity="0.3" />
          </radialGradient>
          <filter id="blur-sm" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="1.5" />
          </filter>
        </defs>

        {/* Edges */}
        {edges.map(([a, b], i) => {
          const na = nodeMap[a];
          const nb = nodeMap[b];
          return (
            <line
              key={i}
              x1={na.cx} y1={na.cy}
              x2={nb.cx} y2={nb.cy}
              stroke="rgba(245,158,11,0.12)"
              strokeWidth="0.8"
            />
          );
        })}

        {/* Pulse dots travelling along edges */}
        {pulses.map(({ delay, dur }, i) => (
          <circle key={`pulse-${i}`} r="2.2" fill="#fbbf24" opacity="0.85" filter="url(#blur-sm)">
            <animateMotion dur={dur} repeatCount="indefinite" begin={delay}>
              <mpath xlinkHref={`#edge-path-${i}`} />
            </animateMotion>
            <animate attributeName="opacity" values="0;0.9;0" dur={dur} repeatCount="indefinite" begin={delay} />
          </circle>
        ))}

        {/* Hidden paths for animateMotion (one per pulse) */}
        {pulses.map(({ edge }, i) => {
          const na = nodeMap[edge[0]];
          const nb = nodeMap[edge[1]];
          return (
            <path
              key={`ep-${i}`}
              id={`edge-path-${i}`}
              d={`M ${na.cx} ${na.cy} L ${nb.cx} ${nb.cy}`}
              stroke="none"
              fill="none"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((n) => (
          <g key={n.id}>
            <circle
              cx={n.cx} cy={n.cy} r="5"
              fill="url(#nodeGlow)"
              className="neural-node"
            />
            <circle
              cx={n.cx} cy={n.cy} r="2.5"
              fill="#fbbf24"
              opacity="0.9"
            />
          </g>
        ))}
      </svg>

      <style>{`
        .neural-wrapper {
          display: flex;
          justify-content: center;
          align-items: center;
          pointer-events: none;
          user-select: none;
        }
        .neural-svg {
          width: 100%;
          max-width: 340px;
          height: auto;
          opacity: 0.7;
        }
        .neural-node {
          animation: nodePulse 3s ease-in-out infinite;
        }
        .neural-node:nth-child(odd) {
          animation-delay: -1.5s;
        }
        @keyframes nodePulse {
          0%, 100% { opacity: 0.5; r: 5; }
          50% { opacity: 1; r: 6.5; }
        }
      `}</style>
    </div>
  );
}
