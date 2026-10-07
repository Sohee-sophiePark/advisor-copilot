import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import { DevApp } from "./DevApp";

createRoot(document.getElementById("root")!).render(<StrictMode><DevApp /></StrictMode>);
