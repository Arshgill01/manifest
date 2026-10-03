import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// UI + mono use the OS's own faces (SF Pro / SF Mono on a Mac); the one web font is bundled, never a CDN,
// so the viewer works with Wi-Fi off
import "@fontsource-variable/newsreader/opsz-italic.css";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
