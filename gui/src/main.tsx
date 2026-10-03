import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// fonts are bundled (no CDN), so the viewer works with Wi-Fi off
import "@fontsource-variable/schibsted-grotesk/wght.css";
import "@fontsource-variable/martian-mono/standard.css";
import "@fontsource-variable/newsreader/opsz-italic.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
