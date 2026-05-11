import Link from "next/link";

const freeTier = [
  "3 beginner lessons per track (18 total)",
  "Beginner quiz for every track",
  "AI Tutor (10 messages/day)",
  "Progress tracking & XP system",
  "Basic market concepts",
  "Community Discord access",
];

const proTier = [
  "All 102 lessons (beginner + intermediate + advanced)",
  "All quizzes with detailed explanations",
  "Unlimited AI Tutor access",
  "Weekly live Q&A with traders",
  "Trade journal template (Google Sheets)",
  "Real-time signal alerts (Telegram)",
  "Downloadable cheat sheets & checklists",
  "Priority support",
];

const eliteTier = [
  "Everything in Pro",
  "1-on-1 monthly strategy session (30 min)",
  "Custom indicator pack (TradingView)",
  "Private Discord with professional traders",
  "Exclusive backtesting walkthroughs",
  "Portfolio review framework",
  "Tax optimization guide",
  "Early access to new courses",
];

const upsells = [
  {
    icon: "📊",
    title: "TradingView Indicator Pack",
    price: "$49",
    desc: "Custom InvestIQ indicators for support/resistance, trend strength, and entry signals.",
    tag: "One-time",
  },
  {
    icon: "📱",
    title: "Signal Alert Service",
    price: "$29/mo",
    desc: "Daily high-probability setups delivered to Telegram with entry, stop, and target.",
    tag: "Add-on",
  },
  {
    icon: "👥",
    title: "InvestIQ Community",
    price: "$19/mo",
    desc: "Active Discord community with daily trade discussions, chart sharing, and accountability.",
    tag: "Add-on",
  },
  {
    icon: "📕",
    title: "Complete Trading Psychology Course",
    price: "$79",
    desc: "Deep-dive 6-hour course covering peak performance, journaling, and identity-based trading.",
    tag: "One-time",
  },
];

const faqs = [
  {
    q: "Is InvestIQ real financial advice?",
    a: "No. InvestIQ is an educational platform. All content is for learning purposes only. Always do your own research (DYOR) and consult a licensed financial advisor before making investment decisions.",
  },
  {
    q: "What if I'm a complete beginner?",
    a: "Perfect starting point. Every track starts from absolute zero — we explain every term, use plain English, and build up gradually. No prior knowledge assumed.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Monthly subscriptions can be canceled anytime from your account settings. No contracts, no cancellation fees. Annual plans are refundable within 30 days.",
  },
  {
    q: "How is this different from YouTube?",
    a: "YouTube gives you disconnected videos with no structure, no testing, and no personalization. InvestIQ gives you a structured curriculum, quizzes to verify learning, AI that answers YOUR questions, and progress tracking — all in one place.",
  },
  {
    q: "Do I need money to start investing to use InvestIQ?",
    a: "Absolutely not. We recommend starting with paper trading (simulated). Most of our students spend months paper trading before using real money — and that's exactly what we recommend.",
  },
];

export default function PricingPage() {
  return (
    <div className="min-h-screen px-4 py-12">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="text-center mb-16">
          <h1 className="text-4xl sm:text-5xl font-black mb-4">
            Simple, transparent pricing
          </h1>
          <p className="text-gray-400 text-lg max-w-xl mx-auto">
            Start free. Upgrade when you&apos;re ready to go deeper.
          </p>
        </div>

        {/* Pricing cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mb-20">
          {/* Free */}
          <div className="glass rounded-2xl border border-white/5 p-7 flex flex-col">
            <div className="mb-6">
              <div className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Free</div>
              <div className="text-4xl font-black text-white mb-1">$0</div>
              <div className="text-sm text-gray-500">Forever free</div>
            </div>
            <ul className="space-y-3 flex-1 mb-8">
              {freeTier.map((item) => (
                <li key={item} className="flex items-start gap-2 text-sm text-gray-400">
                  <span className="text-green-400 mt-0.5 shrink-0">✓</span>
                  {item}
                </li>
              ))}
            </ul>
            <Link href="/learn" className="w-full py-3 rounded-xl font-semibold glass border border-white/10 text-white text-center hover:bg-white/5 transition-colors">
              Get Started Free
            </Link>
          </div>

          {/* Pro (highlighted) */}
          <div className="rounded-2xl border border-orange-500/40 p-7 flex flex-col relative overflow-hidden"
            style={{ background: "linear-gradient(135deg, rgba(249,115,22,0.08), rgba(251,191,36,0.05))" }}>
            <div className="absolute top-0 right-0 bg-orange-500 text-white text-xs font-bold px-3 py-1 rounded-bl-xl">MOST POPULAR</div>
            <div className="mb-6">
              <div className="text-sm font-semibold text-orange-400 uppercase tracking-wider mb-2">Pro</div>
              <div className="flex items-end gap-2 mb-1">
                <div className="text-4xl font-black text-white">$19</div>
                <div className="text-gray-400 mb-1">/month</div>
              </div>
              <div className="text-sm text-gray-500">or $149/year (save 35%)</div>
            </div>
            <ul className="space-y-3 flex-1 mb-8">
              {proTier.map((item) => (
                <li key={item} className="flex items-start gap-2 text-sm text-gray-300">
                  <span className="text-orange-400 mt-0.5 shrink-0">✓</span>
                  {item}
                </li>
              ))}
            </ul>
            <Link href="/learn" className="w-full py-3 rounded-xl font-semibold text-white text-center gradient-crypto hover:opacity-90 transition-opacity">
              Start 7-Day Free Trial
            </Link>
            <p className="text-xs text-center text-gray-500 mt-2">No credit card required</p>
          </div>

          {/* Elite */}
          <div className="glass rounded-2xl border border-purple-500/30 p-7 flex flex-col">
            <div className="mb-6">
              <div className="text-sm font-semibold text-purple-400 uppercase tracking-wider mb-2">Elite</div>
              <div className="flex items-end gap-2 mb-1">
                <div className="text-4xl font-black text-white">$79</div>
                <div className="text-gray-400 mb-1">/month</div>
              </div>
              <div className="text-sm text-gray-500">or $599/year (save 37%)</div>
            </div>
            <ul className="space-y-3 flex-1 mb-8">
              {eliteTier.map((item) => (
                <li key={item} className="flex items-start gap-2 text-sm text-gray-300">
                  <span className="text-purple-400 mt-0.5 shrink-0">✓</span>
                  {item}
                </li>
              ))}
            </ul>
            <Link href="/learn" className="w-full py-3 rounded-xl font-semibold text-white text-center"
              style={{ background: "linear-gradient(135deg, #6366f1, #a855f7)" }}>
              Go Elite
            </Link>
          </div>
        </div>

        {/* Why better than alternatives */}
        <div className="mb-20">
          <h2 className="text-3xl font-black text-center mb-10">Why InvestIQ vs. the alternatives</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th className="pb-4 pr-6 text-gray-400 font-normal">Feature</th>
                  <th className="pb-4 px-4 text-orange-400 font-bold text-center">InvestIQ</th>
                  <th className="pb-4 px-4 text-gray-500 font-normal text-center">YouTube</th>
                  <th className="pb-4 px-4 text-gray-500 font-normal text-center">Udemy Courses</th>
                  <th className="pb-4 px-4 text-gray-500 font-normal text-center">Other Apps</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {[
                  ["Structured curriculum", "✅", "❌", "⚠️", "⚠️"],
                  ["Beginner to advanced path", "✅", "❌", "⚠️", "❌"],
                  ["AI-powered tutoring", "✅", "❌", "❌", "❌"],
                  ["Knowledge quizzes", "✅", "❌", "⚠️", "⚠️"],
                  ["Progress tracking", "✅", "❌", "❌", "✅"],
                  ["Real trade examples", "✅", "⚠️", "⚠️", "❌"],
                  ["Risk-first approach", "✅", "❌", "❌", "❌"],
                  ["Regular updates", "✅", "✅", "❌", "⚠️"],
                  ["Community access", "✅", "❌", "⚠️", "⚠️"],
                  ["Affordable price", "✅ $19/mo", "✅ Free", "✅ One-time", "⚠️ Varies"],
                ].map(([feature, ...cols]) => (
                  <tr key={feature}>
                    <td className="py-3 pr-6 text-gray-400">{feature}</td>
                    {cols.map((val, i) => (
                      <td key={i} className="py-3 px-4 text-center">
                        <span className={i === 0 ? "text-white font-medium" : "text-gray-500"}>{val}</span>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Upsells */}
        <div className="mb-20">
          <h2 className="text-3xl font-black text-center mb-3">Add-ons & Upgrades</h2>
          <p className="text-gray-400 text-center mb-10">Optional tools to accelerate your progress.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {upsells.map((u) => (
              <div key={u.title} className="glass rounded-2xl border border-white/5 p-6 flex gap-4">
                <div className="text-3xl shrink-0">{u.icon}</div>
                <div className="flex-1">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <div>
                      <h3 className="font-bold text-white text-sm">{u.title}</h3>
                      <span className="text-xs text-gray-500">{u.tag}</span>
                    </div>
                    <span className="font-black text-orange-400 shrink-0">{u.price}</span>
                  </div>
                  <p className="text-xs text-gray-400 leading-relaxed">{u.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* FAQ */}
        <div className="mb-20">
          <h2 className="text-3xl font-black text-center mb-10">Frequently Asked Questions</h2>
          <div className="space-y-4 max-w-3xl mx-auto">
            {faqs.map((faq) => (
              <div key={faq.q} className="glass rounded-2xl border border-white/5 p-6">
                <h3 className="font-bold text-white mb-2">{faq.q}</h3>
                <p className="text-sm text-gray-400 leading-relaxed">{faq.a}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Final CTA */}
        <div className="glass rounded-3xl border border-orange-500/20 p-10 sm:p-14 text-center">
          <div className="text-5xl mb-4">💰</div>
          <h2 className="text-3xl font-black mb-3">Start free. Upgrade when ready.</h2>
          <p className="text-gray-400 mb-8 max-w-md mx-auto">20+ free lessons available right now. No credit card. No risk. Just learning.</p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link href="/learn" className="px-8 py-4 rounded-xl font-bold text-white gradient-crypto text-lg hover:opacity-90 transition-opacity">
              Start for Free →
            </Link>
            <Link href="/ai-tutor" className="px-8 py-4 rounded-xl font-bold glass border border-white/10 text-white text-lg hover:bg-white/5 transition-colors">
              Try AI Tutor
            </Link>
          </div>
          <p className="text-xs text-gray-600 mt-4">Educational content only — not financial advice.</p>
        </div>
      </div>
    </div>
  );
}
