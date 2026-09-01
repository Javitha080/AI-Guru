/**
 * Off-screen SVG filter definitions for the liquid-glass surface tier.
 *
 * `backdrop-filter: url(#lg-refraction)` in liquid-glass.css needs these
 * filters to exist somewhere in the document, so this mounts once in the root
 * layout. It is a plain server component — no hooks, no client JS.
 *
 * How the filter works:
 *   feTurbulence     generates a smooth fractal noise field
 *   feGaussianBlur   softens it, so the distortion undulates instead of
 *                    speckling (raw turbulence looks like TV static)
 *   feDisplacementMap pushes each backdrop pixel by the noise's R/G channels,
 *                    which is what makes light appear to bend through the
 *                    panel edge
 *
 * `scale` is the distortion strength in px. Anything past ~40 stops reading
 * as glass and starts reading as a broken GPU, so both presets stay under it.
 */
export default function LiquidGlassDefs() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={0}
      height={0}
      style={{
        position: "absolute",
        width: 0,
        height: 0,
        overflow: "hidden",
        pointerEvents: "none",
      }}
    >
      <defs>
        {/* Default: card and panel edges. */}
        <filter
          id="lg-refraction"
          x="-14%"
          y="-14%"
          width="128%"
          height="128%"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.012 0.018"
            numOctaves={2}
            seed={7}
            result="noise"
          />
          <feGaussianBlur in="noise" stdDeviation="1.4" result="softNoise" />
          <feDisplacementMap
            in="SourceGraphic"
            in2="softNoise"
            scale={26}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>

        {/* Subtle variant for large surfaces (hero, drawers), where the
            default strength would visibly warp text sitting behind them. */}
        <filter
          id="lg-refraction-soft"
          x="-8%"
          y="-8%"
          width="116%"
          height="116%"
          colorInterpolationFilters="sRGB"
        >
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.008 0.012"
            numOctaves={1}
            seed={3}
            result="noiseSoft"
          />
          <feGaussianBlur in="noiseSoft" stdDeviation="2" result="softNoiseSoft" />
          <feDisplacementMap
            in="SourceGraphic"
            in2="softNoiseSoft"
            scale={12}
            xChannelSelector="R"
            yChannelSelector="G"
          />
        </filter>
      </defs>
    </svg>
  );
}
