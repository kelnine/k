"use client";

import { use, useState } from "react";
import Link from "next/link";
import { getCategoryById } from "@/data/categories";
import { getQuiz } from "@/data/quizzes";
import { saveQuizScore } from "@/lib/progress";

interface Props {
  params: Promise<{ category: string }>;
}

export default function QuizPage({ params }: Props) {
  const { category } = use(params);
  const cat = getCategoryById(category);
  const quiz = getQuiz(category, "beginner");

  const [current, setCurrent] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [finished, setFinished] = useState(false);

  if (!cat || !quiz) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400 px-4">
        <div className="text-center">
          <div className="text-4xl mb-4">🚧</div>
          <p className="text-lg font-semibold mb-2">Quiz Coming Soon</p>
          <p className="text-sm mb-6">We&apos;re building this quiz. Check back soon!</p>
          <Link href="/learn" className="px-6 py-3 rounded-xl gradient-crypto text-white font-semibold">Back to Learn</Link>
        </div>
      </div>
    );
  }

  const question = quiz.questions[current];
  const totalQ = quiz.questions.length;
  const score = answers.filter((a, i) => a === quiz.questions[i].correctIndex).length;

  function handleSelect(optionIdx: number) {
    if (selected !== null) return;
    setSelected(optionIdx);
  }

  function handleNext() {
    const newAnswers = [...answers, selected];
    if (current + 1 >= totalQ) {
      setAnswers(newAnswers);
      const finalScore = newAnswers.filter((a, i) => a === quiz!.questions[i].correctIndex).length;
      saveQuizScore(`${category}-beginner`, Math.round((finalScore / totalQ) * 100));
      setFinished(true);
    } else {
      setAnswers(newAnswers);
      setCurrent(current + 1);
      setSelected(null);
    }
  }

  function handleRetry() {
    setCurrent(0);
    setSelected(null);
    setAnswers([]);
    setFinished(false);
  }

  const pct = Math.round((score / totalQ) * 100);

  if (finished) {
    const grade = pct >= 80 ? "Excellent!" : pct >= 60 ? "Good Job!" : "Keep Practicing";
    const gradeColor = pct >= 80 ? "#22c55e" : pct >= 60 ? "#f97316" : "#ef4444";
    const gradeIcon = pct >= 80 ? "🏆" : pct >= 60 ? "⭐" : "📚";

    return (
      <div className="min-h-screen px-4 py-12 flex items-center justify-center">
        <div className="max-w-md w-full">
          <div className="glass rounded-3xl border border-white/5 p-8 text-center">
            <div className="text-6xl mb-4">{gradeIcon}</div>
            <h1 className="text-3xl font-black text-white mb-2">{grade}</h1>
            <p className="text-gray-400 mb-6">You scored {score} out of {totalQ} ({pct}%)</p>

            {/* Score ring */}
            <div className="relative w-32 h-32 mx-auto mb-6">
              <svg className="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
                <circle cx="60" cy="60" r="50" fill="none" stroke="#1e2330" strokeWidth="10" />
                <circle cx="60" cy="60" r="50" fill="none" strokeWidth="10"
                  stroke={gradeColor}
                  strokeDasharray={`${2 * Math.PI * 50}`}
                  strokeDashoffset={`${2 * Math.PI * 50 * (1 - pct / 100)}`}
                  strokeLinecap="round" />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-2xl font-black text-white">{pct}%</span>
              </div>
            </div>

            {/* Question review */}
            <div className="text-left space-y-3 mb-6">
              {quiz.questions.map((q, i) => {
                const isCorrect = answers[i] === q.correctIndex;
                return (
                  <div key={q.id} className={`p-3 rounded-xl text-xs border ${isCorrect ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"}`}>
                    <div className="flex items-start gap-2">
                      <span>{isCorrect ? "✅" : "❌"}</span>
                      <div>
                        <p className="text-gray-300 font-medium mb-1">{q.question}</p>
                        {!isCorrect && <p className="text-gray-400 italic">{q.explanation}</p>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="flex flex-col gap-3">
              <button onClick={handleRetry} className="w-full py-3 rounded-xl font-semibold glass border border-white/10 text-white hover:bg-white/5 transition-colors">
                Retry Quiz
              </button>
              <Link href={`/learn/${category}`} className="w-full py-3 rounded-xl font-semibold text-white text-center" style={{ background: cat.color }}>
                Continue Learning →
              </Link>
              <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-300 transition-colors">
                View my progress →
              </Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen px-4 py-12 flex items-center justify-center">
      <div className="max-w-2xl w-full">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl"
            style={{ background: `${cat.color}20`, border: `1px solid ${cat.color}40` }}>
            {cat.icon}
          </div>
          <div>
            <div className="font-bold text-white">{cat.name} — Beginner Quiz</div>
            <div className="text-xs text-gray-500">Question {current + 1} of {totalQ}</div>
          </div>
        </div>

        {/* Progress bar */}
        <div className="w-full h-1.5 bg-white/5 rounded-full mb-8 overflow-hidden">
          <div className="h-full rounded-full transition-all duration-500" style={{ width: `${((current + 1) / totalQ) * 100}%`, background: cat.color }} />
        </div>

        {/* Question card */}
        <div className="glass rounded-2xl border border-white/5 p-6 sm:p-8 mb-5">
          <h2 className="text-lg sm:text-xl font-bold text-white mb-6 leading-snug">{question.question}</h2>

          <div className="space-y-3">
            {question.options.map((opt, i) => {
              const isSelected = selected === i;
              const isCorrect = i === question.correctIndex;
              const showResult = selected !== null;

              let borderColor = "border-white/10";
              let bg = "hover:bg-white/5";
              let textColor = "text-gray-300";
              if (showResult) {
                if (isCorrect) { borderColor = "border-green-500/50"; bg = "bg-green-500/10"; textColor = "text-green-300"; }
                else if (isSelected && !isCorrect) { borderColor = "border-red-500/50"; bg = "bg-red-500/10"; textColor = "text-red-300"; }
              } else if (isSelected) {
                borderColor = "border-white/30"; bg = "bg-white/5"; textColor = "text-white";
              }

              return (
                <button
                  key={i}
                  onClick={() => handleSelect(i)}
                  disabled={selected !== null}
                  className={`w-full text-left px-5 py-4 rounded-xl border transition-all flex items-center gap-3 ${borderColor} ${bg} ${textColor}`}
                >
                  <div className={`w-7 h-7 rounded-full border flex items-center justify-center text-xs font-bold shrink-0 ${showResult && isCorrect ? "bg-green-500 border-green-500 text-white" : showResult && isSelected && !isCorrect ? "bg-red-500 border-red-500 text-white" : "border-white/20"}`}>
                    {showResult && isCorrect ? "✓" : showResult && isSelected && !isCorrect ? "✗" : String.fromCharCode(65 + i)}
                  </div>
                  <span className="text-sm font-medium">{opt}</span>
                </button>
              );
            })}
          </div>

          {/* Explanation */}
          {selected !== null && (
            <div className={`mt-5 p-4 rounded-xl text-sm ${selected === question.correctIndex ? "bg-green-500/10 border border-green-500/20 text-green-300" : "bg-red-500/10 border border-red-500/20 text-red-300"}`}>
              <span className="font-semibold">{selected === question.correctIndex ? "✅ Correct! " : "❌ Not quite. "}</span>
              <span className="text-gray-300">{question.explanation}</span>
            </div>
          )}
        </div>

        <button
          onClick={handleNext}
          disabled={selected === null}
          className="w-full py-4 rounded-2xl font-bold text-white text-base transition-opacity disabled:opacity-30 hover:opacity-90"
          style={{ background: cat.color }}
        >
          {current + 1 >= totalQ ? "See Results" : "Next Question →"}
        </button>
      </div>
    </div>
  );
}
