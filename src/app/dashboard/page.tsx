"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { categories } from "@/data/categories";
import { learningPaths } from "@/data";
import { getProgress, getLevelTitle, getLevelProgress } from "@/lib/progress";
import { UserProgress } from "@/data/types";

const readyToTradeChecklist = [
  { id: "understand-risk", label: "Understand the 1% risk rule" },
  { id: "set-stop-loss", label: "Always use hard stop losses" },
  { id: "paper-trade", label: "Completed 30+ paper trades" },
  { id: "trading-plan", label: "Written a trading plan" },
  { id: "journal", label: "Started a trading journal" },
  { id: "studied-psychology", label: "Studied trading psychology" },
  { id: "one-strategy", label: "Mastered one strategy (not ten)" },
  { id: "risk-reward", label: "Understand risk/reward ratios" },
];

export default function DashboardPage() {
  const [progress, setProgress] = useState<UserProgress | null>(null);
  const [checklist, setChecklist] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const p = getProgress();
    setProgress(p);
    try {
      const saved = localStorage.getItem("investiq_checklist");
      if (saved) setChecklist(JSON.parse(saved));
    } catch { /* ignore */ }
  }, []);

  function toggleCheck(id: string) {
    const updated = { ...checklist, [id]: !checklist[id] };
    setChecklist(updated);
    localStorage.setItem("investiq_checklist", JSON.stringify(updated));
  }

  if (!progress) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-purple-500 border-t-transparent animate-spin" />
      </div>
    );
  }

  const levelInfo = getLevelProgress(progress.xp);
  const checkCount = Object.values(checklist).filter(Boolean).length;
  const checkPct = Math.round((checkCount / readyToTradeChecklist.length) * 100);

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <h1 className="text-3xl font-black mb-1">Your Dashboard</h1>
          <p className="text-gray-400">Track your learning journey and skill progression.</p>
        </div>

        {/* Top stats */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <div className="glass rounded-2xl border border-white/5 p-5 text-center">
            <div className="text-3xl font-black text-gradient-gold mb-1">{progress.xp}</div>
            <div className="text-xs text-gray-500">Total XP</div>
          </div>
          <div className="glass rounded-2xl border border-white/5 p-5 text-center">
            <div className="text-3xl font-black text-white mb-1">{getLevelTitle(progress.xp)}</div>
            <div className="text-xs text-gray-500">Trader Rank</div>
          </div>
          <div className="glass rounded-2xl border border-white/5 p-5 text-center">
            <div className="text-3xl font-black text-gradient-green mb-1">{progress.completedLessons.length}</div>
            <div className="text-xs text-gray-500">Lessons Done</div>
          </div>
          <div className="glass rounded-2xl border border-white/5 p-5 text-center">
            <div className="text-3xl font-black text-white mb-1">{Object.keys(progress.quizScores).length}</div>
            <div className="text-xs text-gray-500">Quizzes Taken</div>
          </div>
        </div>

        {/* XP Progress to next level */}
        <div className="glass rounded-2xl border border-purple-500/20 p-6 mb-8">
          <div className="flex items-center justify-between mb-3">
            <div>
              <span className="font-bold text-white">{getLevelTitle(progress.xp)}</span>
              <span className="text-gray-500 mx-2">→</span>
              <span className="text-gray-400">{getLevelTitle(progress.xp + levelInfo.next - levelInfo.current + 1)}</span>
            </div>
            <span className="text-sm text-purple-400 font-semibold">{levelInfo.current} / {levelInfo.next} XP</span>
          </div>
          <div className="w-full h-3 bg-white/5 rounded-full overflow-hidden">
            <div className="progress-bar h-full" style={{ width: `${levelInfo.pct}%` }} />
          </div>
          <p className="text-xs text-gray-500 mt-2">{levelInfo.next - levelInfo.current} XP to next rank</p>
        </div>

        {/* Category progress */}
        <h2 className="text-xl font-bold mb-4">Learning Track Progress</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
          {categories.map((cat) => {
            const path = learningPaths[cat.id];
            if (!path) return null;
            const allLessons = path.levels.flatMap((l) => l.lessons.map((ls) => `${cat.id}-${l.id}-${ls.id}`));
            const done = allLessons.filter((id) => progress.completedLessons.includes(id)).length;
            const pct = allLessons.length > 0 ? Math.round((done / allLessons.length) * 100) : 0;
            const quizScore = progress.quizScores[`${cat.id}-beginner`];

            return (
              <Link key={cat.id} href={`/learn/${cat.id}`} className="glass rounded-2xl border p-5 hover:border-white/10 transition-all lesson-card" style={{ borderColor: `${cat.color}20` }}>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl"
                    style={{ background: `${cat.color}20`, border: `1px solid ${cat.color}40` }}>
                    {cat.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-white text-sm">{cat.name}</div>
                    <div className="text-xs text-gray-500">{done}/{allLessons.length} lessons</div>
                  </div>
                  <div className="text-sm font-bold" style={{ color: cat.color }}>{pct}%</div>
                </div>
                <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden mb-3">
                  <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: cat.color }} />
                </div>
                {quizScore !== undefined && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-500">
                    <span>🎯</span> Quiz score: <span className="font-semibold" style={{ color: quizScore >= 80 ? "#22c55e" : quizScore >= 60 ? "#f97316" : "#ef4444" }}>{quizScore}%</span>
                  </div>
                )}
              </Link>
            );
          })}
        </div>

        {/* Ready to Trade Checklist */}
        <div className="glass rounded-2xl border border-teal-500/20 p-6 mb-8">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-xl font-bold text-white">Ready to Trade? Checklist</h2>
              <p className="text-sm text-gray-400 mt-0.5">Complete these milestones before risking real money.</p>
            </div>
            <div className="text-right">
              <div className="text-2xl font-black" style={{ color: checkPct === 100 ? "#22c55e" : "#14b8a6" }}>{checkPct}%</div>
              <div className="text-xs text-gray-500">{checkCount}/{readyToTradeChecklist.length} done</div>
            </div>
          </div>

          <div className="space-y-3">
            {readyToTradeChecklist.map((item) => (
              <button key={item.id} onClick={() => toggleCheck(item.id)} className="w-full flex items-center gap-3 text-left group">
                <div className={`w-6 h-6 rounded-lg border-2 flex items-center justify-center shrink-0 transition-all ${checklist[item.id] ? "bg-teal-500 border-teal-500" : "border-white/20 group-hover:border-white/40"}`}>
                  {checklist[item.id] && <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                </div>
                <span className={`text-sm transition-colors ${checklist[item.id] ? "text-gray-500 line-through" : "text-gray-300 group-hover:text-white"}`}>{item.label}</span>
              </button>
            ))}
          </div>

          {checkPct === 100 && (
            <div className="mt-5 p-4 rounded-xl bg-green-500/10 border border-green-500/20 text-center">
              <div className="text-2xl mb-1">🎉</div>
              <p className="font-bold text-green-400">You&apos;re ready to start paper trading!</p>
              <p className="text-xs text-gray-400 mt-1">Remember: 30+ paper trades before real money. Consistency first.</p>
            </div>
          )}
        </div>

        {/* Quiz Scores */}
        {Object.keys(progress.quizScores).length > 0 && (
          <div className="glass rounded-2xl border border-white/5 p-6 mb-8">
            <h2 className="text-xl font-bold mb-4">Quiz Scores</h2>
            <div className="space-y-3">
              {Object.entries(progress.quizScores).map(([key, score]) => {
                const [catId, levelId] = key.split("-");
                const cat = categories.find((c) => c.id === catId);
                if (!cat) return null;
                return (
                  <div key={key} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span>{cat.icon}</span>
                      <span className="text-sm text-gray-300">{cat.name} — {levelId}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="w-24 h-1.5 bg-white/5 rounded-full overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${score}%`, background: score >= 80 ? "#22c55e" : score >= 60 ? "#f97316" : "#ef4444" }} />
                      </div>
                      <span className="text-sm font-bold w-10 text-right" style={{ color: score >= 80 ? "#22c55e" : score >= 60 ? "#f97316" : "#ef4444" }}>{score}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* CTA if no progress */}
        {progress.completedLessons.length === 0 && (
          <div className="glass rounded-2xl border border-orange-500/20 p-8 text-center">
            <div className="text-4xl mb-3">🚀</div>
            <h3 className="text-xl font-bold text-white mb-2">Start Your First Lesson</h3>
            <p className="text-gray-400 mb-5">Pick a track and begin earning XP. Your progress will appear here.</p>
            <Link href="/learn" className="inline-block px-8 py-3 rounded-xl font-bold text-white gradient-crypto">Browse Tracks →</Link>
          </div>
        )}
      </div>
    </div>
  );
}
