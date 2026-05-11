"use client";

import { UserProgress } from "@/data/types";

const STORAGE_KEY = "investiq_progress";

const defaultProgress: UserProgress = {
  completedLessons: [],
  xp: 0,
  level: "Novice",
  streakDays: 0,
  quizScores: {},
  lastActiveDate: "",
};

export function getProgress(): UserProgress {
  if (typeof window === "undefined") return defaultProgress;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultProgress;
    return { ...defaultProgress, ...JSON.parse(raw) };
  } catch {
    return defaultProgress;
  }
}

export function saveProgress(progress: UserProgress): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
}

export function completeLesson(lessonId: string, xpGain: number): UserProgress {
  const progress = getProgress();
  if (!progress.completedLessons.includes(lessonId)) {
    progress.completedLessons.push(lessonId);
    progress.xp += xpGain;
    progress.level = getLevelTitle(progress.xp);
  }
  progress.lastActiveDate = new Date().toISOString().split("T")[0];
  saveProgress(progress);
  return progress;
}

export function saveQuizScore(quizKey: string, score: number): UserProgress {
  const progress = getProgress();
  progress.quizScores[quizKey] = Math.max(progress.quizScores[quizKey] ?? 0, score);
  saveProgress(progress);
  return progress;
}

export function getLevelTitle(xp: number): string {
  if (xp < 200) return "Novice";
  if (xp < 500) return "Apprentice";
  if (xp < 1000) return "Analyst";
  if (xp < 2000) return "Trader";
  if (xp < 4000) return "Strategist";
  return "Market Wizard";
}

export function getLevelProgress(xp: number): { current: number; next: number; pct: number } {
  const thresholds = [0, 200, 500, 1000, 2000, 4000, 999999];
  for (let i = 0; i < thresholds.length - 1; i++) {
    if (xp < thresholds[i + 1]) {
      const current = xp - thresholds[i];
      const next = thresholds[i + 1] - thresholds[i];
      return { current, next, pct: Math.round((current / next) * 100) };
    }
  }
  return { current: xp, next: xp, pct: 100 };
}

export function isLessonCompleted(lessonId: string): boolean {
  return getProgress().completedLessons.includes(lessonId);
}
