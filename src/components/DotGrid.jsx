import { useRef, useEffect, useCallback, useMemo } from 'react';

/**
 * DotGrid - Animated dot grid background
 * Simplified version without InertiaPlugin (which is paid)
 */

function hexToRgb(hex) {
    const m = hex.match(/^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
    if (!m) return { r: 0, g: 0, b: 0 };
    return {
        r: parseInt(m[1], 16),
        g: parseInt(m[2], 16),
        b: parseInt(m[3], 16)
    };
}

const DotGrid = ({
    dotSize = 8,
    gap = 40,
    baseColor = '#334155',     // slate-700
    activeColor = '#6366f1',   // indigo-500
    proximity = 120,
    className = '',
}) => {
    const wrapperRef = useRef(null);
    const canvasRef = useRef(null);
    const dotsRef = useRef([]);
    const pointerRef = useRef({ x: -1000, y: -1000 });
    const rafRef = useRef(null);

    const baseRgb = useMemo(() => hexToRgb(baseColor), [baseColor]);
    const activeRgb = useMemo(() => hexToRgb(activeColor), [activeColor]);

    const buildGrid = useCallback(() => {
        const wrap = wrapperRef.current;
        const canvas = canvasRef.current;
        if (!wrap || !canvas) return;

        const { width, height } = wrap.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2); // Cap at 2x for performance

        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext('2d');
        if (ctx) ctx.scale(dpr, dpr);

        const cols = Math.floor((width + gap) / (dotSize + gap));
        const rows = Math.floor((height + gap) / (dotSize + gap));
        const cell = dotSize + gap;

        const gridW = cell * cols - gap;
        const gridH = cell * rows - gap;

        const startX = (width - gridW) / 2 + dotSize / 2;
        const startY = (height - gridH) / 2 + dotSize / 2;

        const dots = [];
        for (let y = 0; y < rows; y++) {
            for (let x = 0; x < cols; x++) {
                const cx = startX + x * cell;
                const cy = startY + y * cell;
                dots.push({ cx, cy, xOffset: 0, yOffset: 0 });
            }
        }
        dotsRef.current = dots;
    }, [dotSize, gap]);

    // Mobile detection
    const isMobile = useMemo(() => {
        if (typeof window !== 'undefined') {
            return window.matchMedia('(hover: none) and (pointer: coarse)').matches;
        }
        return false;
    }, []);

    // Animation loop
    useEffect(() => {
        const proxSq = proximity * proximity;

        const draw = () => {
            const canvas = canvasRef.current;
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            if (!ctx) return;

            const { width, height } = canvas.getBoundingClientRect();
            ctx.clearRect(0, 0, width, height);

            let px, py;

            if (isMobile) {
                // Automatic "breathing" or moving spotlight pattern for mobile
                const time = performance.now() / 2000; // Speed control
                // Move in a figure-8 or similar pattern
                px = width / 2 + Math.sin(time) * (width / 3);
                py = height / 2 + Math.cos(time * 1.3) * (height / 4);
            } else {
                px = pointerRef.current.x;
                py = pointerRef.current.y;
            }

            for (const dot of dotsRef.current) {
                const dx = dot.cx - px;
                const dy = dot.cy - py;
                const dsq = dx * dx + dy * dy;

                let fillColor = baseColor;
                let scale = 1;

                if (dsq <= proxSq) {
                    const dist = Math.sqrt(dsq);
                    const t = 1 - dist / proximity;
                    const r = Math.round(baseRgb.r + (activeRgb.r - baseRgb.r) * t);
                    const g = Math.round(baseRgb.g + (activeRgb.g - baseRgb.g) * t);
                    const b = Math.round(baseRgb.b + (activeRgb.b - baseRgb.b) * t);
                    fillColor = `rgb(${r},${g},${b})`;
                    scale = 1 + t * 0.5; // Dots grow slightly when hovered/active
                }

                ctx.beginPath();
                ctx.arc(dot.cx, dot.cy, (dotSize / 2) * scale, 0, Math.PI * 2);
                ctx.fillStyle = fillColor;
                ctx.fill();
            }

            rafRef.current = requestAnimationFrame(draw);
        };

        draw();
        return () => {
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
        };
    }, [proximity, baseColor, baseRgb, activeRgb, dotSize, isMobile]);

    // Build grid on mount and resize
    useEffect(() => {
        buildGrid();

        const handleResize = () => {
            buildGrid();
        };

        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, [buildGrid]);

    // Mouse tracking (throttled) - Only needed for non-mobile but harmless to leave
    useEffect(() => {
        if (isMobile) return; // Skip mouse listeners on mobile

        let lastCall = 0;

        const onMove = (e) => {
            const now = performance.now();
            if (now - lastCall < 32) return; // ~30fps throttle
            lastCall = now;

            const canvas = canvasRef.current;
            if (!canvas) return;

            const rect = canvas.getBoundingClientRect();
            pointerRef.current.x = e.clientX - rect.left;
            pointerRef.current.y = e.clientY - rect.top;
        };

        const onLeave = () => {
            pointerRef.current.x = -1000;
            pointerRef.current.y = -1000;
        };

        window.addEventListener('mousemove', onMove, { passive: true });
        window.addEventListener('mouseleave', onLeave);

        return () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseleave', onLeave);
        };
    }, [isMobile]);

    return (
        <div ref={wrapperRef} className={`fixed inset-0 overflow-hidden pointer-events-none ${className}`}>
            <canvas
                ref={canvasRef}
                className="absolute inset-0 w-full h-full"
            />
        </div>
    );
};

export default DotGrid;
