/** Generates a rainbow HSL color cycling through hue. */
export function rainbowColor(step: number): string {
  // Cycle through hue 0-360, each step is ~37 degrees (10 colors)
  const hue = (step * 37 + Date.now() / 30) % 360;
  return `hsl(${hue}, 70%, 55%)`;
}

/** Minimal rainbow animation for glowing borders. */
export const RAINBOW_KEYFRAMES = `
@keyframes rainbow-glow {
  0%   { box-shadow: 0 0 6px hsl(0, 70%, 55%, 0.5), 0 0 2px hsl(0, 70%, 55%, 0.3); }
  14%  { box-shadow: 0 0 6px hsl(50, 70%, 55%, 0.5), 0 0 2px hsl(50, 70%, 55%, 0.3); }
  28%  { box-shadow: 0 0 6px hsl(100, 70%, 55%, 0.5), 0 0 2px hsl(100, 70%, 55%, 0.3); }
  42%  { box-shadow: 0 0 6px hsl(150, 70%, 55%, 0.5), 0 0 2px hsl(150, 70%, 55%, 0.3); }
  57%  { box-shadow: 0 0 6px hsl(200, 70%, 55%, 0.5), 0 0 2px hsl(200, 70%, 55%, 0.3); }
  71%  { box-shadow: 0 0 6px hsl(250, 70%, 55%, 0.5), 0 0 2px hsl(250, 70%, 55%, 0.3); }
  85%  { box-shadow: 0 0 6px hsl(300, 70%, 55%, 0.5), 0 0 2px hsl(300, 70%, 55%, 0.3); }
  100% { box-shadow: 0 0 6px hsl(360, 70%, 55%, 0.5), 0 0 2px hsl(360, 70%, 55%, 0.3); }
}
`;
