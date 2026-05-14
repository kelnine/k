import { notFound } from "next/navigation";
import Link from "next/link";
import { getCategoryById } from "@/data/categories";
import { getLearningPath } from "@/data";
import LessonClient from "@/components/lessons/LessonClient";

interface Props {
  params: Promise<{ category: string; level: string; lesson: string }>;
}

export default async function LessonPage({ params }: Props) {
  const { category, level, lesson } = await params;
  const cat = getCategoryById(category);
  const path = getLearningPath(category);
  const levelData = path?.levels.find((l) => l.id === level);
  const lessonData = levelData?.lessons.find((ls) => ls.id === lesson);

  if (!cat || !levelData || !lessonData) notFound();

  const lessonIndex = levelData.lessons.findIndex((l) => l.id === lesson);
  const prevLesson = lessonIndex > 0 ? levelData.lessons[lessonIndex - 1] : null;
  const nextLesson = lessonIndex < levelData.lessons.length - 1 ? levelData.lessons[lessonIndex + 1] : null;

  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-3xl mx-auto">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-gray-500 mb-8 flex-wrap">
          <Link href="/learn" className="hover:text-white transition-colors">Learn</Link>
          <span>/</span>
          <Link href={`/learn/${category}`} className="hover:text-white transition-colors" style={{ color: cat.color }}>{cat.name}</Link>
          <span>/</span>
          <Link href={`/learn/${category}/${level}`} className="hover:text-white transition-colors">{levelData.label}</Link>
          <span>/</span>
          <span className="text-gray-300 truncate max-w-[200px]">{lessonData.title}</span>
        </div>

        <LessonClient
          lesson={lessonData}
          cat={cat}
          level={level}
          category={category}
          prevLesson={prevLesson ? { id: prevLesson.id, title: prevLesson.title } : null}
          nextLesson={nextLesson ? { id: nextLesson.id, title: nextLesson.title } : null}
        />
      </div>
    </div>
  );
}
