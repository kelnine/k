import Link from "next/link";
import { categories } from "@/data/categories";

export default function LearnPage() {
  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-6xl mx-auto">
        <div className="mb-10">
          <h1 className="text-4xl font-black mb-3">Choose Your Track</h1>
          <p className="text-gray-400 text-lg">Select a discipline and start learning from beginner to advanced.</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {categories.map((cat) => (
            <Link
              key={cat.id}
              href={`/learn/${cat.id}`}
              className={`lesson-card glass rounded-2xl p-7 border ${cat.borderColor} group transition-all`}
            >
              <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-3xl mb-5"
                style={{ background: `${cat.color}20`, border: `1px solid ${cat.color}40` }}>
                {cat.icon}
              </div>
              <h2 className="text-xl font-bold text-white mb-2">{cat.name}</h2>
              <p className="text-sm text-gray-400 mb-5 leading-relaxed">{cat.description}</p>

              <div className="flex items-center justify-between mb-5">
                <div className="text-center">
                  <div className="text-lg font-bold text-white">{cat.totalLessons}</div>
                  <div className="text-xs text-gray-500">Lessons</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-white">{cat.estimatedHours}h</div>
                  <div className="text-xs text-gray-500">Content</div>
                </div>
                <div className="text-center">
                  <div className="text-lg font-bold text-white">3</div>
                  <div className="text-xs text-gray-500">Levels</div>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 mb-5">
                {cat.tags.map((tag) => (
                  <span key={tag} className="text-xs px-2.5 py-1 rounded-full font-medium"
                    style={{ background: `${cat.color}15`, color: cat.color }}>
                    {tag}
                  </span>
                ))}
              </div>

              <div className="flex items-center gap-2 font-semibold text-sm" style={{ color: cat.color }}>
                View Learning Path
                <svg className="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
