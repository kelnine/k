import { notFound } from "next/navigation";
import Link from "next/link";
import { getCategoryById } from "@/data/categories";
import { getLearningPath } from "@/data";

interface Props {
  params: Promise<{ category: string }>;
}

const levelColors: Record<string, string> = {
  beginner: "#22c55e",
  intermediate: "#f97316",
  advanced: "#ef4444",
};

const levelIcons: Record<string, string> = {
  beginner: "🌱",
  intermediate: "⚡",
  advanced: "🔥",
};

export default async function CategoryPage({ params }: Props) {
  const { category } = await params;
  const cat = getCategoryById(category);
  const path = getLearningPath(category);

  if (!cat || !path) notFound();

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-4xl mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-8">
          <Link href="/learn" className="hover:text-white transition-colors">Learn</Link>
          <span>/</span>
          <span style={{ color: cat.color }}>{cat.name}</span>
        </div>

        {/* Header */}
        <div className="glass rounded-3xl border p-8 mb-8 relative overflow-hidden" style={{ borderColor: `${cat.color}30` }}>
          <div className="absolute top-0 right-0 w-64 h-64 rounded-full opacity-5 blur-3xl pointer-events-none"
            style={{ background: `radial-gradient(circle, ${cat.color}, transparent)` }} />
          <div className="relative flex items-start gap-6">
            <div className="w-20 h-20 rounded-2xl flex items-center justify-center text-4xl shrink-0"
              style={{ background: `${cat.color}20`, border: `1px solid ${cat.color}40` }}>
              {cat.icon}
            </div>
            <div className="flex-1">
              <h1 className="text-3xl font-black text-white mb-2">{cat.name}</h1>
              <p className="text-gray-400 leading-relaxed mb-4">{cat.description}</p>
              <div className="flex flex-wrap gap-4 text-sm">
                <span className="flex items-center gap-1.5 text-gray-400">
                  <span>📚</span> {cat.totalLessons} lessons
                </span>
                <span className="flex items-center gap-1.5 text-gray-400">
                  <span>⏱️</span> ~{cat.estimatedHours} hours
                </span>
                <span className="flex items-center gap-1.5 text-gray-400">
                  <span>🎯</span> 3 skill levels
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Levels */}
        <div className="space-y-6">
          {path.levels.map((level, idx) => (
            <div key={level.id} className="glass rounded-2xl border border-white/5 overflow-hidden">
              {/* Level header */}
              <div className="px-6 py-5 border-b border-white/5 flex items-center justify-between"
                style={{ background: `${levelColors[level.id]}08` }}>
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{levelIcons[level.id]}</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-white">Level {idx + 1}: {level.label}</h2>
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ background: `${levelColors[level.id]}20`, color: levelColors[level.id] }}>
                        {level.subtitle}
                      </span>
                    </div>
                    <p className="text-sm text-gray-500 mt-0.5">{level.lessons.length} lessons</p>
                  </div>
                </div>
                <Link
                  href={`/learn/${category}/${level.id}`}
                  className="px-4 py-2 rounded-lg text-sm font-semibold text-white transition-opacity hover:opacity-80"
                  style={{ background: levelColors[level.id] }}
                >
                  {idx === 0 ? "Start" : "Continue"}
                </Link>
              </div>

              {/* Level details */}
              <div className="px-6 py-5 grid grid-cols-1 md:grid-cols-3 gap-6">
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Key Concepts</h3>
                  <ul className="space-y-1.5">
                    {level.keyConcepts.map((c) => (
                      <li key={c} className="text-sm text-gray-300 flex items-start gap-2">
                        <span style={{ color: levelColors[level.id] }} className="mt-0.5">•</span>
                        {c}
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">What You&apos;ll Learn</h3>
                  <p className="text-sm text-gray-400 leading-relaxed">{level.whatYouLearn}</p>
                </div>
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Real-World Application</h3>
                  <p className="text-sm text-gray-400 leading-relaxed">{level.realWorldApp}</p>
                </div>
              </div>

              {/* Lesson list */}
              <div className="px-6 pb-5 space-y-2">
                {level.lessons.map((lesson, lessonIdx) => (
                  <Link
                    key={lesson.id}
                    href={`/learn/${category}/${level.id}/${lesson.id}`}
                    className="flex items-center justify-between p-3 rounded-xl hover:bg-white/5 transition-colors group border border-white/0 hover:border-white/5"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold shrink-0"
                        style={{ background: `${levelColors[level.id]}20`, color: levelColors[level.id] }}>
                        {lessonIdx + 1}
                      </div>
                      <span className="text-sm text-gray-300 group-hover:text-white transition-colors">{lesson.title}</span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <span className="text-xs text-gray-500">{lesson.duration}</span>
                      <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: `${levelColors[level.id]}15`, color: levelColors[level.id] }}>
                        +{lesson.xp} XP
                      </span>
                      <svg className="w-4 h-4 text-gray-600 group-hover:text-gray-300 group-hover:translate-x-0.5 transition-all" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                      </svg>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Quiz CTA */}
        <div className="mt-8 glass rounded-2xl border p-6 flex flex-col sm:flex-row items-center justify-between gap-4" style={{ borderColor: `${cat.color}30` }}>
          <div>
            <h3 className="font-bold text-white mb-1">Ready to test your knowledge?</h3>
            <p className="text-sm text-gray-400">Take the beginner quiz and earn XP toward your trader rank.</p>
          </div>
          <Link
            href={`/quiz/${category}`}
            className="px-6 py-3 rounded-xl font-semibold text-white shrink-0"
            style={{ background: cat.color }}
          >
            Take Quiz →
          </Link>
        </div>
      </div>
    </div>
  );
}
