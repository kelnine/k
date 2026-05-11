import { notFound } from "next/navigation";
import Link from "next/link";
import { getCategoryById } from "@/data/categories";
import { getLearningPath } from "@/data";

interface Props {
  params: Promise<{ category: string; level: string }>;
}

const levelColors: Record<string, string> = {
  beginner: "#22c55e",
  intermediate: "#f97316",
  advanced: "#ef4444",
};

export default async function LevelPage({ params }: Props) {
  const { category, level } = await params;
  const cat = getCategoryById(category);
  const path = getLearningPath(category);
  const levelData = path?.levels.find((l) => l.id === level);

  if (!cat || !levelData) notFound();

  const color = levelColors[level] ?? cat.color;

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-3xl mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-8 flex-wrap">
          <Link href="/learn" className="hover:text-white transition-colors">Learn</Link>
          <span>/</span>
          <Link href={`/learn/${category}`} className="hover:text-white transition-colors" style={{ color: cat.color }}>{cat.name}</Link>
          <span>/</span>
          <span style={{ color }}>{levelData.label}</span>
        </div>

        {/* Level header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <span className="text-xs font-semibold px-3 py-1 rounded-full" style={{ background: `${color}20`, color }}>
              {levelData.label}
            </span>
            <span className="text-xs text-gray-500">{levelData.subtitle}</span>
          </div>
          <h1 className="text-3xl font-black text-white mb-3">{levelData.label} {cat.name}</h1>
          <p className="text-gray-400 leading-relaxed">{levelData.whatYouLearn}</p>
        </div>

        {/* Lessons */}
        <div className="space-y-3 mb-10">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
            {levelData.lessons.length} Lessons
          </h2>
          {levelData.lessons.map((lesson, idx) => (
            <Link
              key={lesson.id}
              href={`/learn/${category}/${level}/${lesson.id}`}
              className="flex items-center gap-4 glass rounded-2xl border border-white/5 p-5 group hover:border-white/10 transition-all lesson-card"
            >
              <div className="w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold shrink-0"
                style={{ background: `${color}20`, color }}>
                {idx + 1}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-white group-hover:text-white text-sm sm:text-base truncate">{lesson.title}</h3>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-xs text-gray-500">⏱ {lesson.duration}</span>
                  <span className="text-xs font-medium" style={{ color }}>+{lesson.xp} XP</span>
                </div>
              </div>
              <svg className="w-5 h-5 text-gray-600 group-hover:text-gray-300 group-hover:translate-x-1 transition-all shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </Link>
          ))}
        </div>

        {/* Quiz CTA */}
        <div className="glass rounded-2xl border p-6 text-center" style={{ borderColor: `${color}30` }}>
          <h3 className="font-bold text-white mb-2">Completed all lessons?</h3>
          <p className="text-sm text-gray-400 mb-4">Take the quiz to solidify your knowledge and earn bonus XP.</p>
          <Link href={`/quiz/${category}`}
            className="inline-block px-6 py-3 rounded-xl font-semibold text-white" style={{ background: color }}>
            Take {levelData.label} Quiz →
          </Link>
        </div>
      </div>
    </div>
  );
}
