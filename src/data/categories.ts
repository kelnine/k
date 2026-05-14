export interface Category {
  id: string;
  name: string;
  description: string;
  icon: string;
  color: string;
  glowClass: string;
  gradientClass: string;
  textColor: string;
  borderColor: string;
  bgColor: string;
  totalLessons: number;
  estimatedHours: number;
  tags: string[];
}

export const categories: Category[] = [
  {
    id: "crypto",
    name: "Crypto Investing",
    description: "Master Bitcoin, altcoins, DeFi, and on-chain analysis from scratch.",
    icon: "₿",
    color: "#f97316",
    glowClass: "glow-orange",
    gradientClass: "gradient-crypto",
    textColor: "text-orange-400",
    borderColor: "border-orange-500/30",
    bgColor: "bg-orange-500/10",
    totalLessons: 18,
    estimatedHours: 12,
    tags: ["Bitcoin", "DeFi", "Altcoins", "Wallets"],
  },
  {
    id: "forex",
    name: "Forex Trading",
    description: "Learn currency pairs, pips, leverage, and global market dynamics.",
    icon: "💱",
    color: "#3b82f6",
    glowClass: "glow-blue",
    gradientClass: "gradient-forex",
    textColor: "text-blue-400",
    borderColor: "border-blue-500/30",
    bgColor: "bg-blue-500/10",
    totalLessons: 18,
    estimatedHours: 14,
    tags: ["EUR/USD", "Pips", "Leverage", "Sessions"],
  },
  {
    id: "stocks",
    name: "Stock Market",
    description: "Understand equities, fundamental analysis, and building a portfolio.",
    icon: "📈",
    color: "#22c55e",
    glowClass: "glow-green",
    gradientClass: "gradient-stocks",
    textColor: "text-green-400",
    borderColor: "border-green-500/30",
    bgColor: "bg-green-500/10",
    totalLessons: 18,
    estimatedHours: 13,
    tags: ["Equities", "Dividends", "S&P 500", "ETFs"],
  },
  {
    id: "options",
    name: "Options Trading",
    description: "Calls, puts, Greeks, and advanced strategies like spreads and condors.",
    icon: "⚡",
    color: "#a855f7",
    glowClass: "glow-purple",
    gradientClass: "gradient-options",
    textColor: "text-purple-400",
    borderColor: "border-purple-500/30",
    bgColor: "bg-purple-500/10",
    totalLessons: 18,
    estimatedHours: 16,
    tags: ["Calls", "Puts", "Greeks", "IV"],
  },
  {
    id: "psychology",
    name: "Trading Psychology",
    description: "Conquer fear, greed, and FOMO. Build the mindset of a pro trader.",
    icon: "🧠",
    color: "#ec4899",
    glowClass: "glow-pink",
    gradientClass: "gradient-psychology",
    textColor: "text-pink-400",
    borderColor: "border-pink-500/30",
    bgColor: "bg-pink-500/10",
    totalLessons: 15,
    estimatedHours: 8,
    tags: ["Mindset", "Discipline", "Emotions", "Journal"],
  },
  {
    id: "risk",
    name: "Risk Management",
    description: "Position sizing, stop losses, and protecting your capital at all costs.",
    icon: "🛡️",
    color: "#14b8a6",
    glowClass: "glow-teal",
    gradientClass: "gradient-risk",
    textColor: "text-teal-400",
    borderColor: "border-teal-500/30",
    bgColor: "bg-teal-500/10",
    totalLessons: 15,
    estimatedHours: 9,
    tags: ["Position Size", "Stop Loss", "R:R", "Drawdown"],
  },
];

export function getCategoryById(id: string): Category | undefined {
  return categories.find((c) => c.id === id);
}
