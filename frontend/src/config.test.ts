import { describe, expect, it } from "vitest";
import { resolveApiBase, resolveWsBase } from "./config";

describe("backend URLs", () => {
  it("defaults to the local backend", () => {
    expect(resolveApiBase(undefined)).toBe("http://localhost:8000");
    expect(resolveWsBase(undefined, "http://localhost:8000")).toBe("ws://localhost:8000");
  });

  it("strips trailing slashes from the API URL", () => {
    expect(resolveApiBase("https://agentflow-api.onrender.com/")).toBe("https://agentflow-api.onrender.com");
  });

  it("derives a secure WebSocket URL from an https API", () => {
    expect(resolveWsBase(undefined, "https://agentflow-api.onrender.com")).toBe("wss://agentflow-api.onrender.com");
  });

  it("keeps an explicit WebSocket URL", () => {
    expect(resolveWsBase("wss://ws.example.com/", "https://api.example.com")).toBe("wss://ws.example.com");
  });
});
