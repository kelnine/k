import { cryptoPath } from "./lessons/crypto";
import { forexPath } from "./lessons/forex";
import { stocksPath } from "./lessons/stocks";
import { optionsPath } from "./lessons/options";
import { psychologyPath } from "./lessons/psychology";
import { riskPath } from "./lessons/risk";
import { LearningPath } from "./types";

export const learningPaths: Record<string, LearningPath> = {
  crypto: cryptoPath,
  forex: forexPath,
  stocks: stocksPath,
  options: optionsPath,
  psychology: psychologyPath,
  risk: riskPath,
};

export function getLearningPath(categoryId: string): LearningPath | undefined {
  return learningPaths[categoryId];
}
