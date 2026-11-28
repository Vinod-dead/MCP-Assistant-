/** Static export: `next build` writes frontend/out, which scripts/sync_frontend.py copies into the Python package
 *  so FastAPI can serve the dashboard (users do not need Node.js to *run* Studio). */
const dev = process.env.NODE_ENV !== "production";
export default {
  output: dev ? undefined : "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
};
