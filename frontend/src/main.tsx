import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter/wght.css";
import App from "./App";
import "./index.css";
import "./theme.css";
import "./brand.css";
import "./chat.css";

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
