import React from "react";
import { TERMS } from "./glossary.js";

/** Jargon with a hover/focus definition. */
export default function Term({ k, children }) {
  const tip = TERMS[k];
  if (!tip) return <>{children ?? k}</>;
  return <span className="term" tabIndex={0} data-tip={tip}>{children ?? k}</span>;
}
