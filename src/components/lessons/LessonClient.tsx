"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { Lesson } from "@/data/types";
import { Category } from "@/data/categories";
import { completeLesson, isLessonCompleted } from "@/lib/progress";

interface Props {
  lesson: Lesson;
  cat: Category;
  level: string;
  category: string;
  prevLesson: { id: string; title: string } | null;
  nextLesson: { id: string; title: string } | null;
}

const levelColors: Record<string, string> = {
  beginner: "#22c55e",
  intermediate: "#f97316",
  advanced: "#ef4444",
};

export default function LessonClient({ lesson, cat, level, category, prevLesson, nextLesson }: Props) {
  const [completed, setCompleted] = useState(false);
  const [showConfetti, setShowConfetti] = useState(false);
  const color = levelColors[level] ?? cat.color;

  useEffect(() => {
    setCompleted(isLessonCompleted(`${category}-${level}-${lesson.id}`));
  }, [category, level, lesson.id]);

  function handleComplete() {
    const result = completeLesson(`${category}-${level}-${lesson.id}`, lesson.xp);
    setCompleted(true);
    setShowConfetti(true);
    setTimeout(() => setShowConfetti(false), 3000);
    void result;
  }

  const paragraphs = lesson.content.split("\n\n");

  return (
    <article>
      {/* Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-xs font-semibold px-3 py-1 rounded-full" style={{ background: `${cat.color}20`, color: cat.color }}>
            {cat.name}
          </span>
          <span className="text-xs text-gray-500">⏱ {lesson.duration}</span>
          <span className="text-xs font-medium" style={{ color }}>+{lesson.xp} XP</span>
          {completed && (
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-green-500/20 text-green-400">✓ Completed</span>
          )}
        </div>
        <h1 className="text-2xl sm:text-3xl font-black text-white leading-tight">{lesson.title}</h1>
      </div>

      {/* Content */}
      <div className="glass rounded-2xl border border-white/5 p-6 sm:p-8 mb-6 prose-custom">
        {paragraphs.map((para, i) => {
          const isHeading = para.match(/^[A-Z][A-Z\s/&()+]+:?\s*$/m) || para.match(/^[A-Z][A-Z\s]+\s\([^)]+\):/);
          if (para.startsWith("•") || para.includes("\n•")) {
            const lines = para.split("\n");
            return (
              <div key={i} className="mb-4">
                {lines.map((line, j) => (
                  <p key={j} className={`text-sm sm:text-base leading-relaxed ${line.startsWith("•") ? "text-gray-300 pl-4 mb-1" : "text-gray-300 mb-2"}`}>
                    {line.startsWith("•") ? (
                      <>
                        <span style={{ color }} className="mr-2 font-bold">•</span>
                        {line.slice(1).trim()}
                      </>
                    ) : line}
                  </p>
                ))}
              </div>
            );
          }
          if (isHeading) {
            return (
              <h2 key={i} className="text-xs font-bold tracking-widest uppercase mb-3 mt-6 first:mt-0" style={{ color }}>
                {para.trim()}
              </h2>
            );
          }
          return (
            <div key={i} className="mb-4">
              {para.split("\n").map((line, j) => (
                <p key={j} className="text-sm sm:text-base leading-relaxed text-gray-300 mb-1.5">{line}</p>
              ))}
            </div>
          );
        })}
      </div>

      {/* Example */}
      <div className="glass rounded-2xl border mb-6 overflow-hidden" style={{ borderColor: `${cat.color}30` }}>
        <div className="px-5 py-3 border-b flex items-center gap-2" style={{ borderColor: `${cat.color}20`, background: `${cat.color}08` }}>
          <span className="text-base">📊</span>
          <span className="text-sm font-semibold" style={{ color: cat.color }}>Real Example: {lesson.example.title}</span>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm sm:text-base text-gray-300 leading-relaxed">{lesson.example.body}</p>
        </div>
      </div>

      {/* Action Step */}
      <div className="glass rounded-2xl border mb-8 overflow-hidden" style={{ borderColor: `${color}30` }}>
        <div className="px-5 py-3 border-b flex items-center gap-2" style={{ borderColor: `${color}20`, background: `${color}08` }}>
          <span className="text-base">🎯</span>
          <span className="text-sm font-semibold" style={{ color }}>Your Action Step</span>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm sm:text-base text-gray-300 leading-relaxed">{lesson.actionStep}</p>
        </div>
      </div>

      {/* Complete button */}
      {!completed ? (
        <button
          onClick={handleComplete}
          className="w-full py-4 rounded-2xl font-bold text-white text-lg mb-8 transition-opacity hover:opacity-90"
          style={{ background: `linear-gradient(135deg, ${cat.color}, ${color})` }}
        >
          {showConfetti ? "🎉 Lesson Complete! +{lesson.xp} XP" : `Mark as Complete (+${lesson.xp} XP)`}
        </button>
      ) : (
        <div className="w-full py-4 rounded-2xl font-bold text-center text-lg mb-8 bg-green-500/20 text-green-400 border border-green-500/30">
          ✓ Completed — Great work!
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between gap-4">
        {prevLesson ? (
          <Link
            href={`/learn/${category}/${level}/${prevLesson.id}`}
            className="flex-1 glass rounded-xl border border-white/5 px-4 py-3 text-sm hover:border-white/10 transition-colors"
          >
            <div className="text-xs text-gray-500 mb-1">← Previous</div>
            <div className="text-gray-300 font-medium truncate">{prevLesson.title}</div>
          </Link>
        ) : <div className="flex-1" />}

        {nextLesson ? (
          <Link
            href={`/learn/${category}/${level}/${nextLesson.id}`}
            className="flex-1 glass rounded-xl border border-white/10 px-4 py-3 text-sm text-right hover:border-white/20 transition-colors"
            style={{ borderColor: `${color}30` }}
          >
            <div className="text-xs mb-1" style={{ color }}>Next →</div>
            <div className="text-white font-medium truncate">{nextLesson.title}</div>
          </Link>
        ) : (
          <Link
            href={`/quiz/${category}`}
            className="flex-1 rounded-xl px-4 py-3 text-sm text-right font-semibold text-white"
            style={{ background: cat.color }}
          >
            <div className="text-xs mb-1 opacity-80">Level Complete!</div>
            <div className="font-bold">Take the Quiz →</div>
          </Link>
        )}
      </div>

      {/* AI Tutor CTA */}
      <div className="mt-8 glass rounded-2xl border border-purple-500/20 p-5 flex items-center justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-white mb-1">Have questions about this lesson?</div>
          <div className="text-xs text-gray-400">Ask the AI Tutor for deeper explanations, examples, or practice questions.</div>
        </div>
        <Link
          href={`/ai-tutor?lesson=${encodeURIComponent(lesson.title)}`}
          className="shrink-0 px-4 py-2 rounded-lg text-sm font-semibold text-white"
          style={{ background: "linear-gradient(135deg, #6366f1, #a855f7)" }}
        >
          Ask AI →
        </Link>
      </div>
    </article>
  );
}
