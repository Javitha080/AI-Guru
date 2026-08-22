/**
 * ThemeScript - Initializes theme from localStorage before React hydration
 * This prevents the flash of wrong theme on page load.
 *
 * Must be a Server Component: in Next.js / React 19, <script> tags rendered
 * by Client Components are inert on the client. Rendering it from the server
 * inlines the snippet into the SSR HTML so the browser executes it before
 * hydration.
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        const stored = localStorage.getItem('aiguru-theme') || localStorage.getItem('deeptutor-theme');

        document.documentElement.classList.remove('dark', 'theme-glass', 'theme-snow');

        let theme = stored;
        if (theme === 'snow' || theme === 'cream') theme = 'light';
        if (theme === 'glass') theme = 'dark';

        if (theme === 'dark') {
          document.documentElement.classList.add('dark');
          localStorage.setItem('aiguru-theme', 'dark');
        } else if (theme === 'light') {
          // already clean
          localStorage.setItem('aiguru-theme', 'light');
        } else {
          // Default to OLED Dark theme
          document.documentElement.classList.add('dark');
          localStorage.setItem('aiguru-theme', 'dark');
        }
      } catch (e) {
        /* localStorage may be disabled */
      }
    })();
  `;

  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}
