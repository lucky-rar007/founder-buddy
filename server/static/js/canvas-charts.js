/**
 * CanvasCharts — Dynamic High-Resolution HTML5 Canvas Charts & Health Gauges.
 * 
 * Features:
 * - Glowing radial gauge arcs with smooth progress interpolation
 * - Dynamic color transitions based on health score (Emerald, Indigo, Amber, Crimson)
 * - Animated Sparkline / Signal Wave Canvas Renderer
 * - Retina resolution DPI auto-scaling
 */

const CanvasCharts = (() => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    /**
     * Render an animated cluster health gauge onto a target Canvas element.
     */
    function renderClusterGauge(canvas, score = 95, trend = 'stable', label = '') {
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const w = 84;
        const h = 84;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;

        ctx.scale(dpr, dpr);

        const centerX = w / 2;
        const centerY = h / 2;
        const radius = 32;
        const lineWidth = 6;

        // Color selection based on score
        let strokeColor = '#10B981'; // Emerald 500
        let glowColor = 'rgba(16, 185, 129, 0.35)';

        if (score < 50) {
            strokeColor = '#EF4444'; // Red 500
            glowColor = 'rgba(239, 68, 68, 0.4)';
        } else if (score < 80) {
            strokeColor = '#F59E0B'; // Amber 500
            glowColor = 'rgba(245, 158, 11, 0.4)';
        }

        // Animation target state
        let currentScore = 0;
        const duration = 1000; // 1 second arc draw animation
        const startTime = performance.now();

        function drawFrame(now) {
            const elapsed = now - startTime;
            const progress = Math.min(elapsed / duration, 1);
            // Ease-out cubic ease curve
            const easedProgress = 1 - Math.pow(1 - progress, 3);
            currentScore = score * easedProgress;

            ctx.clearRect(0, 0, w, h);

            // 1. Draw Track Arc (Background Ring)
            ctx.strokeStyle = 'rgba(191, 192, 192, 0.25)';
            ctx.lineWidth = lineWidth;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
            ctx.stroke();

            // 2. Draw Active Score Arc with Gradient & Glow
            const startAngle = -Math.PI / 2;
            const endAngle = startAngle + (Math.PI * 2 * (currentScore / 100));

            ctx.save();
            ctx.shadowColor = glowColor;
            ctx.shadowBlur = 10;

            const grad = ctx.createLinearGradient(0, 0, w, h);
            grad.addColorStop(0, strokeColor);
            grad.addColorStop(1, '#EF8354');

            ctx.strokeStyle = grad;
            ctx.lineWidth = lineWidth;
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.arc(centerX, centerY, radius, startAngle, endAngle);
            ctx.stroke();
            ctx.restore();

            // 3. Draw Center Text
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = '800 13px "JetBrains Mono", monospace';
            ctx.fillStyle = '#FFFFFF';
            ctx.fillText(`${Math.round(currentScore)}%`, centerX, centerY);

            if (progress < 1) {
                requestAnimationFrame(drawFrame);
            }
        }

        requestAnimationFrame(drawFrame);
    }

    /**
     * Render an animated Canvas Signal Wave Sparkline.
     */
    function renderSignalWave(canvas, dataPoints = [40, 65, 55, 80, 72, 95, 88, 100]) {
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const rect = canvas.getBoundingClientRect();
        const w = rect.width || 200;
        const h = rect.height || 50;

        canvas.width = w * dpr;
        canvas.height = h * dpr;
        ctx.scale(dpr, dpr);

        ctx.clearRect(0, 0, w, h);

        if (dataPoints.length < 2) return;

        const maxVal = Math.max(...dataPoints, 100);
        const minVal = Math.min(...dataPoints, 0);
        const stepX = w / (dataPoints.length - 1);

        // Convert points to coordinates
        const points = dataPoints.map((val, idx) => {
            const normY = (val - minVal) / (maxVal - minVal || 1);
            return {
                x: idx * stepX,
                y: h - normY * (h - 12) - 6
            };
        });

        // 1. Fill gradient below wave
        const fillGrad = ctx.createLinearGradient(0, 0, 0, h);
        fillGrad.addColorStop(0, 'rgba(239, 131, 84, 0.3)');
        fillGrad.addColorStop(1, 'rgba(79, 93, 117, 0.0)');

        ctx.fillStyle = fillGrad;
        ctx.beginPath();
        ctx.moveTo(points[0].x, h);
        ctx.lineTo(points[0].x, points[0].y);

        for (let i = 0; i < points.length - 1; i++) {
            const xc = (points[i].x + points[i + 1].x) / 2;
            const yc = (points[i].y + points[i + 1].y) / 2;
            ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
        }
        ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
        ctx.lineTo(w, h);
        ctx.closePath();
        ctx.fill();

        // 2. Draw glowing stroke line
        ctx.save();
        ctx.shadowColor = 'rgba(239, 131, 84, 0.45)';
        ctx.shadowBlur = 8;
        ctx.strokeStyle = '#EF8354';
        ctx.lineWidth = 2.5;

        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);

        for (let i = 0; i < points.length - 1; i++) {
            const xc = (points[i].x + points[i + 1].x) / 2;
            const yc = (points[i].y + points[i + 1].y) / 2;
            ctx.quadraticCurveTo(points[i].x, points[i].y, xc, yc);
        }
        ctx.lineTo(points[points.length - 1].x, points[points.length - 1].y);
        ctx.stroke();
        ctx.restore();
    }

    return {
        renderClusterGauge,
        renderSignalWave
    };
})();
