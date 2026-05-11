import Link from "next/link";
import { categories } from "@/data/categories";

const stats = [
  { value: "6", label: "Learning Tracks" },
  { value: "102", label: "Lessons" },
  { value: "3", label: "Levels Each" },
  { value: "AI", label: "Powered Tutor" },
];

const testimonials = [
  {
    quote: "I went from knowing nothing about options to selling covered calls every month. The lessons actually make sense.",
    name: "Marcus T.",
    role: "Software Engineer → Part-time Trader",
    avatar: "M",
    color: "bg-purple-500",
  },
  {
    quote: "The trading psychology module changed how I think about losses. I stopped revenge trading completely.",
    name: "Priya K.",
    role: "Nurse → Forex Trader",
    avatar: "P",
    color: "bg-pink-500",
  },
  {
    quote: "The AI tutor explains chart patterns in plain English. It's like having a mentor available 24/7.",
    name: "James O.",
    role: "Accountant → Stock Investor",
    avatar: "J",
    color: "bg-green-500",
  },
];

const features = [
  { icon: "🧭", title: "Structured Paths", desc: "Beginner to advanced in 6 disciplines. No guessing what to learn next." },
  { icon: "🤖", title: "AI Tutor (Claude)", desc: "Ask anything — chart analysis, trade ideas, concept explanations — in seconds." },
  { icon: "🎯", title: "Quizzes & XP", desc: "Test your knowledge with targeted quizzes. Earn XP and level up your trader rank." },
  { icon: "📊", title: "Real Examples", desc: "Every lesson includes real market scenarios, not hypothetical fluff." },
  { icon: "🛡️", title: "Risk-First Design", desc: "Capital preservation is lesson one. We teach you to survive before you thrive." },
  { icon: "📱", title: "Learn Anywhere", desc: "Bite-sized lessons designed for busy people. 8–20 minutes each." },
];

export default function HomePage() {
  return (
    <div className="min-h-screen">
      {/* Hero */}
      <section className="relative overflow-hidden px-4 pt-20 pb-32 sm:pt-32 sm:pb-40">
        <div
          className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[500px] rounded-full opacity-10 blur-3xl pointer-events-none"
          style={{ background: "radial-gradient(circle, #f97316 0%, #a855f7 50%, transparent 70%)" }}
        />
        <div className="relative max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold mb-8 glass border border-orange-500/20 text-orange-400">
            <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse-soft" />
            AI-Powered Investing Education
          </div>
          <h1 className="text-4xl sm:text-6xl lg:text-7xl font-black tracking-tight mb-6 leading-[1.05]">
            Learn to invest like<br />
            <span className="text-gradient-gold">a professional.</span>
          </h1>
          <p className="text-lg sm:text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            From Bitcoin basics to options Greeks — structured beginner-to-advanced learning paths with AI-powered coaching and real-world examples.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/learn" className="px-8 py-4 rounded-xl font-bold text-white gradient-crypto text-lg hover:opacity-90 transition-opacity shadow-lg">
              Start Learning Free →
            </Link>
            <Link href="/ai-tutor" className="px-8 py-4 rounded-xl font-bold glass border border-white/10 text-white text-lg hover:bg-white/5 transition-colors">
              Try AI Tutor
            </Link>
          </div>
          <p className="text-sm text-gray-600 mt-4">No credit card required · 20+ free lessons</p>
        </div>
      </section>

      {/* Stats */}
      <section className="px-4 pb-20">
        <div className="max-w-4xl mx-auto grid grid-cols-2 sm:grid-cols-4 gap-4">
          {stats.map((s) => (
            <div key={s.label} className="glass rounded-2xl p-6 text-center border border-white/5">
              <div className="text-3xl sm:text-4xl font-black text-gradient-gold mb-1">{s.value}</div>
              <div className="text-sm text-gray-400">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Categories */}
      <section className="px-4 pb-24">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-black mb-3">Choose your learning track</h2>
            <p className="text-gray-400">Six disciplines. Every level. One platform.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {categories.map((cat) => (
              <Link
                key={cat.id}
                href={`/learn/${cat.id}`}
                className={`lesson-card glass rounded-2xl p-6 border ${cat.borderColor} group transition-all`}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="w-14 h-14 rounded-xl flex items-center justify-center text-2xl"
                    style={{ background: `${cat.color}20`, border: `1px solid ${cat.color}40` }}>
                    {cat.icon}
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-gray-500">{cat.totalLessons} lessons</div>
                    <div className="text-xs text-gray-500">{cat.estimatedHours}h content</div>
                  </div>
                </div>
                <h3 className="text-lg font-bold mb-2 text-white">{cat.name}</h3>
                <p className="text-sm text-gray-400 mb-4 leading-relaxed">{cat.description}</p>
                <div className="flex flex-wrap gap-1.5 mb-4">
                  {cat.tags.map((tag) => (
                    <span key={tag} className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: `${cat.color}15`, color: cat.color }}>
                      {tag}
                    </span>
                  ))}
                </div>
                <div className="flex items-center gap-1.5 text-sm font-semibold" style={{ color: cat.color }}>
                  Start Learning
                  <svg className="w-4 h-4 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="px-4 pb-24">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-black mb-3">Why InvestIQ beats everything else</h2>
            <p className="text-gray-400">Built for people who want to actually trade — not just watch videos.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {features.map((f) => (
              <div key={f.title} className="glass rounded-2xl p-6 border border-white/5">
                <div className="text-3xl mb-3">{f.icon}</div>
                <h3 className="font-bold text-white mb-2">{f.title}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* AI Feature Highlight */}
      <section className="px-4 pb-24">
        <div className="max-w-5xl mx-auto">
          <div className="glass rounded-3xl border border-purple-500/20 p-8 sm:p-12 overflow-hidden relative">
            <div className="absolute top-0 right-0 w-[400px] h-[400px] rounded-full opacity-5 blur-3xl pointer-events-none"
              style={{ background: "radial-gradient(circle, #a855f7, transparent)" }} />
            <div className="relative grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
              <div>
                <div className="text-xs font-semibold text-purple-400 mb-3 tracking-widest uppercase">AI Tutor</div>
                <h2 className="text-3xl sm:text-4xl font-black mb-4">
                  Your personal<br /><span className="text-gradient-blue">market mentor</span>
                </h2>
                <p className="text-gray-400 leading-relaxed mb-6">
                  Powered by Claude AI. Ask anything about any chart, strategy, or concept. Get clear, beginner-friendly answers — or deep technical analysis.
                </p>
                <div className="flex flex-col gap-2 mb-6">
                  {['"Explain this chart pattern to me"', '"What should I look for before entering a trade?"', '"Give me a beginner crypto strategy"', '"Why did my stop loss get hit?"'].map((q) => (
                    <div key={q} className="flex items-center gap-2 text-sm text-gray-300">
                      <span className="text-purple-400">→</span> {q}
                    </div>
                  ))}
                </div>
                <Link href="/ai-tutor" className="inline-flex items-center gap-2 px-6 py-3 rounded-xl font-bold text-white"
                  style={{ background: "linear-gradient(135deg, #6366f1, #a855f7)" }}>
                  Try AI Tutor Free →
                </Link>
              </div>
              {/* Mock chat */}
              <div className="rounded-2xl border border-white/5 overflow-hidden" style={{ background: "rgba(0,0,0,0.4)" }}>
                <div className="px-4 py-3 border-b border-white/5 flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-red-500" />
                  <div className="w-2 h-2 rounded-full bg-yellow-500" />
                  <div className="w-2 h-2 rounded-full bg-green-500" />
                  <span className="ml-2 text-xs text-gray-500">InvestIQ AI Tutor</span>
                </div>
                <div className="p-4 space-y-3">
                  <div className="flex justify-end">
                    <div className="chat-bubble-user rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-gray-200 max-w-[85%]">
                      What is the RSI indicator and when should I use it?
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <div className="w-7 h-7 rounded-full gradient-options flex items-center justify-center text-xs text-white shrink-0 mt-1">AI</div>
                    <div className="chat-bubble-ai rounded-2xl rounded-tl-sm px-4 py-2.5 text-sm text-gray-200 max-w-[85%]">
                      <p className="mb-2">RSI measures momentum on a 0–100 scale:</p>
                      <p className="mb-1">📈 <strong>Above 70</strong> = Overbought (potential sell zone)</p>
                      <p className="mb-1">📉 <strong>Below 30</strong> = Oversold (potential buy zone)</p>
                      <p className="mt-2 text-gray-400 text-xs">Best used with S&R for confirmation. Want a real example?</p>
                    </div>
                  </div>
                </div>
                <div className="px-4 py-3 border-t border-white/5">
                  <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/5 text-sm text-gray-500">
                    Ask anything about markets...
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="px-4 pb-24">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl sm:text-4xl font-black mb-3">Traders who leveled up</h2>
            <p className="text-gray-400">Real people, real progress.</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {testimonials.map((t) => (
              <div key={t.name} className="glass rounded-2xl p-6 border border-white/5">
                <div className="flex mb-3">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <svg key={i} className="w-4 h-4 text-yellow-400" fill="currentColor" viewBox="0 0 20 20">
                      <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
                    </svg>
                  ))}
                </div>
                <p className="text-sm text-gray-300 mb-4 leading-relaxed italic">"{t.quote}"</p>
                <div className="flex items-center gap-3">
                  <div className={`w-9 h-9 rounded-full ${t.color} flex items-center justify-center text-white font-bold text-sm`}>{t.avatar}</div>
                  <div>
                    <div className="text-sm font-semibold text-white">{t.name}</div>
                    <div className="text-xs text-gray-500">{t.role}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-4 pb-24">
        <div className="max-w-3xl mx-auto text-center glass rounded-3xl border border-orange-500/20 p-10 sm:p-16">
          <div className="text-5xl mb-4">🚀</div>
          <h2 className="text-3xl sm:text-4xl font-black mb-4">
            Start your journey today.<br /><span className="text-gradient-gold">It&apos;s free.</span>
          </h2>
          <p className="text-gray-400 mb-8 max-w-lg mx-auto">
            Join thousands of learners building real market skills — not just watching YouTube tutorials.
          </p>
          <Link href="/learn" className="inline-block px-10 py-4 rounded-xl font-bold text-white text-lg gradient-crypto hover:opacity-90 transition-opacity">
            Choose Your Track →
          </Link>
          <p className="text-xs text-gray-600 mt-4">20+ free lessons · No credit card · Cancel anytime</p>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 px-4 py-10">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg gradient-crypto flex items-center justify-center text-white font-black text-xs">IQ</div>
            <span className="font-bold text-sm">InvestIQ</span>
          </div>
          <p className="text-xs text-gray-600 text-center">Educational platform only. Not financial advice. Always DYOR and manage your risk.</p>
          <div className="flex items-center gap-4 text-xs text-gray-600">
            <Link href="/pricing" className="hover:text-gray-400 transition-colors">Pricing</Link>
            <Link href="/ai-tutor" className="hover:text-gray-400 transition-colors">AI Tutor</Link>
            <Link href="/learn" className="hover:text-gray-400 transition-colors">Learn</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
