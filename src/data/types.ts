export interface QuizQuestion {
  id: string;
  question: string;
  options: string[];
  correctIndex: number;
  explanation: string;
}

export interface LessonExample {
  title: string;
  body: string;
}

export interface Lesson {
  id: string;
  title: string;
  duration: string;
  xp: number;
  content: string;
  example: LessonExample;
  actionStep: string;
  quiz: string[];
}

export interface Level {
  id: "beginner" | "intermediate" | "advanced";
  label: string;
  subtitle: string;
  color: string;
  keyConcepts: string[];
  whatYouLearn: string;
  realWorldApp: string;
  lessons: Lesson[];
}

export interface LearningPath {
  categoryId: string;
  levels: Level[];
}

export interface QuizSet {
  categoryId: string;
  levelId: string;
  questions: QuizQuestion[];
}

export interface UserProgress {
  completedLessons: string[];
  xp: number;
  level: string;
  streakDays: number;
  quizScores: Record<string, number>;
  lastActiveDate: string;
}
