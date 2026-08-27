import test from "node:test";
import assert from "node:assert/strict";
import { mapAgentModeToOrb } from "../components/ui/GuruThinkingOrb";

test("mapAgentModeToOrb maps reasoning and thinking modes to breathing", () => {
  const result1 = mapAgentModeToOrb("reasoning");
  assert.equal(result1.state, "breathing");
  assert.equal(result1.label, "AI Guru Thinking…");

  const result2 = mapAgentModeToOrb("thinking", "Guru");
  assert.equal(result2.state, "breathing");
  assert.equal(result2.label, "Guru Thinking…");
});

test("mapAgentModeToOrb maps solving and math to solving", () => {
  const solveResult = mapAgentModeToOrb("deep_solve");
  assert.equal(solveResult.state, "solving");
  assert.equal(solveResult.label, "AI Guru Solving…");

  const mathResult = mapAgentModeToOrb("math");
  assert.equal(mathResult.state, "solving");
});

test("mapAgentModeToOrb maps listening and vision to listening", () => {
  const listeningResult = mapAgentModeToOrb("listening");
  assert.equal(listeningResult.state, "listening");
  assert.equal(listeningResult.label, "Agent listening…");

  const visionResult = mapAgentModeToOrb("vision");
  assert.equal(visionResult.state, "listening");
});

test("mapAgentModeToOrb maps tool execution to working", () => {
  const toolResult = mapAgentModeToOrb("tool_using");
  assert.equal(toolResult.state, "working");
  assert.equal(toolResult.label, "Tool Working…");
});

test("mapAgentModeToOrb maps explore and search to searching", () => {
  const exploreResult = mapAgentModeToOrb("exploring");
  assert.equal(exploreResult.state, "searching");
  assert.equal(exploreResult.label, "AI Guru Searching…");

  const searchResult = mapAgentModeToOrb("web_search");
  assert.equal(searchResult.state, "searching");
});

test("mapAgentModeToOrb maps drafting and writing to composing", () => {
  const draftResult = mapAgentModeToOrb("drafting");
  assert.equal(draftResult.state, "composing");
  assert.equal(draftResult.label, "AI Guru Composing…");
});

test("mapAgentModeToOrb maps planning to shaping", () => {
  const planResult = mapAgentModeToOrb("planning");
  assert.equal(planResult.state, "shaping");
  assert.equal(planResult.label, "AI Guru Planning…");
});

test("mapAgentModeToOrb maps subagent and mcp to connecting", () => {
  const connectResult = mapAgentModeToOrb("connecting");
  assert.equal(connectResult.state, "connecting");
  assert.equal(connectResult.label, "Connecting Agents…");
});

test("mapAgentModeToOrb maps reflecting and quizzing to weaving", () => {
  const reflectResult = mapAgentModeToOrb("reflecting");
  assert.equal(reflectResult.state, "weaving");
  assert.equal(reflectResult.label, "AI Guru Reflecting…");
});
