import { useQuery } from "@tanstack/react-query";
import { BookOpen, FileText, Printer } from "lucide-react";
import { useState } from "react";
import { api } from "../../api";
import { escapePrintText, openPrintWindow, writePrintReport } from "../../shared/lib/print";
import type { AuthConfiguration } from "../../types";

type Guide = { id: string; title: string; audience: string; sections: { heading: string; items: string[] }[] };

const GUIDES: Guide[] = [
  {
    id: "guard",
    title: "راهنمای یک‌صفحه‌ای نگهبان",
    audience: "نگهبان گشت پیاده",
    sections: [
      { heading: "آغاز شیفت", items: ["گوشی سازمانی باید شارژ کامل باشد.", "وارد شوید و رمز محلی خود را بزنید.", "دور گشت را فقط از صف شروع کنید."] },
      { heading: "در هر ایستگاه", items: ["فقط ایستگاه بعدی را می‌بینید؛ همان را بازدید کنید.", "تگ را لمس یا اسکن کنید و تا پایان زمان توقف بمانید.", "به پرسش‌های ایستگاه پاسخ دهید؛ شماره پلمب را دقیق بنویسید."] },
      { heading: "ایمنی", items: ["پیش از ایستگاه H2S یا گاز قابل اشتعال، روشن بودن گازسنج را تأیید کنید. اگر گازسنج هشدار داد، دور شوید.", "صفحه گوشی را در طول دور روشن نگه دارید؛ با قفل‌شدن صفحه، پایش حرکت ممکن است متوقف شود.", "اگر گوشی لرزید و شمارش معکوس شروع شد و حالتان خوب است، آن را لغو کنید."] },
      { heading: "خطر و کمک", items: ["دکمه «اعلام خطر» را بزنید؛ روی صفحه قفل هم کار می‌کند.", "«دریافت شد» یعنی سرور پیام را گرفت. «در حال پیگیری» یعنی اپراتور دید. اگر دومی نیامد، با تماس‌های اضطراری محوطه تماس بگیرید.", "اگر کسی شما را مجبور می‌کند، به‌جای رمز عادی، رمز اضطرار را بزنید. اپ عادی رفتار می‌کند."] },
      { heading: "گزارش و پیام", items: ["پیام فوری را با «دریافت شد» تأیید کنید.", "خسارت، مهمات عمل‌نکرده یا پهپاد: نزدیک نشوید؛ از فاصله امن گزارش کنید.", "در حضورشماری فقط «سالمم» یا «کمک لازم دارم» را بزنید."] },
      { heading: "قطع سامانه", items: ["اپ اسکن‌ها را نگه می‌دارد و بعداً می‌فرستد.", "اگر اپ کار نکرد، فرم کاغذی پشتیبان را با ساعت دقیق پر کنید و به سرپرست تحویل دهید."] },
    ],
  },
  {
    id: "supervisor",
    title: "راهنمای سرپرست شیفت",
    audience: "سرپرست شیفت و مسئول حراست",
    sections: [
      { heading: "روال هر شیفت", items: ["تابلوی استثنا صفحه اصلی نظارت است؛ ابتدا موارد بحرانی و زیاد را بررسی کنید.", "اسکن‌های دستی و در انتظار بازبینی را حضوری تأیید یا رد کنید؛ دلیل را بنویسید.", "تحویل و تحول شیفت را پیش از شروع دور ثبت و تأیید کنید."] },
      { heading: "اضطرار", items: ["وضعیت اضطرار محوطه فقط با مسئول حراست فعال می‌شود و مهلت ایستگاه‌ها را تعلیق می‌کند.", "مهلت‌های تعلیق‌شده جدا گزارش می‌شوند و ازدست‌رفته نیستند.", "حضورشماری را آغاز و فهرست بی‌پاسخ‌ها را پیگیری کنید."] },
      { heading: "قواعد یکپارچگی", items: ["یافته‌ها در حالت سایه‌اند و فقط نشانه‌اند، نه حکم. پیش از هر اقدام انضباطی، شواهد را بررسی و با نگهبان گفت‌وگو کنید.", "تکرار شمارنده تگ یا اسکن یک تگ از دو مکان دور را برای بازدید فیزیکی ایستگاه ارجاع دهید."] },
      { heading: "فرم کاغذی و گزارش", items: ["ردیف‌های فرم کاغذی را با شماره سریال در «ورود فرم کاغذی» ثبت کنید؛ اعتماد آن کم است.", "نمای فردی فقط برای سرپرست همان محوطه و ممیز است و هر مشاهده ثبت می‌شود.", "هر خروجی گزارش ممیزی می‌شود؛ برچسب طبقه‌بندی را رعایت کنید."] },
    ],
  },
  {
    id: "operator",
    title: "راهنمای اپراتور مرکز",
    audience: "اپراتور مرکز فرماندهی",
    sections: [
      { heading: "اعلام خطر", items: ["رسید اعلام خطر را فوراً ثبت کنید؛ بی‌رسید ماندن به سرپرست و سپس مسئول حراست تشدید می‌شود.", "سامانه اعزام خودکار ندارد؛ هر اعزام تصمیم انسانی است."] },
      { heading: "پیام و گزارش", items: ["پیام فوری تا رسید صریح نگهبان در فهرست تشدید می‌ماند.", "رسید هر واحد مخاطب گزارش (حراست، HSE، بهره‌برداری) را پس از اطلاع‌رسانی واقعی ثبت کنید.", "رسانه خسارت، مهمات و پهپاد فقط برای مدیر حراست است و خروجی ندارد."] },
      { heading: "فرمان پیامکی تجهیز", items: ["پیش از ارسال، متن دقیق پیامک و شماره سیم‌کارت را در پیش‌نمایش بررسی کنید.", "درگاه پیامک متصل نیست؛ تحویل در این نسخه نمایشی است."] },
      { heading: "قطع سرویس", items: ["در قطع سامانه طبق دستورالعمل حالت تنزل‌یافته عمل کنید و ثبت دستی را بعداً وارد کنید."] },
    ],
  },
];

function guideBody(guide: Guide) {
  return guide.sections
    .map((s) => `<h3>${escapePrintText(s.heading)}</h3><ul>${s.items.map((i) => `<li>${escapePrintText(i)}</li>`).join("")}</ul>`)
    .join("");
}

function paperFormBody() {
  const rows = Array.from({ length: 12 }, (_, i) => `<tr><td>${i + 1}</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>`).join("");
  return `<div class="grid"><div><small>شماره سریال فرم</small><b>&nbsp;</b></div><div><small>محوطه</small><b>&nbsp;</b></div><div><small>نام نگهبان</small><b>&nbsp;</b></div><div><small>تاریخ (شمسی)</small><b>&nbsp;</b></div></div>
<p class="muted">فقط هنگام قطع سامانه یا شبکه. ساعت دقیق هر بازدید را بنویسید. این فرم بعداً با روش «کاغذی» و اعتماد کم در سامانه ثبت می‌شود.</p>
<table><tr><th>ردیف</th><th>کد ایستگاه</th><th>ساعت دقیق</th><th>شماره پلمب / قرائت</th><th>وضعیت (عادی / ناهنجار)</th><th>امضای نگهبان</th><th>ملاحظات</th></tr>${rows}</table>
<div class="grid"><div><small>امضای سرپرست تحویل‌گیرنده</small><b>&nbsp;</b></div><div><small>تاریخ ورود به سامانه</small><b>&nbsp;</b></div><div><small>ورودکننده</small><b>&nbsp;</b></div><div><small>شناسه ممیزی ورود</small><b>&nbsp;</b></div></div>`;
}

export default function GuidesPage() {
  const config = useQuery({ queryKey: ["guides", "config"], queryFn: () => api<AuthConfiguration>("/auth/config") });
  const [error, setError] = useState("");
  const label = config.data?.classification_label || "";
  const print = (title: string, body: string) => {
    try {
      writePrintReport(openPrintWindow(), {
        title,
        header: `<div class="classification">${escapePrintText(label)}</div><h1>${escapePrintText(title)}</h1>`,
        generatedAt: new Date().toISOString(),
        body,
        footer: `${label} · سپهر حراست`,
      });
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <section className="supervision">
      {error && <div className="error-banner">{error}</div>}
      <div className="report-cards">
        <article className="report-card">
          <header><b><FileText size={16} /> فرم کاغذی پشتیبان گشت</b><small>برای قطع سامانه یا شبکه</small></header>
          <p>دوازده ردیف بازدید با ساعت دقیق، پلمب و امضا؛ ورود بعدی از صفحه نظارت با روش «کاغذی».</p>
          <footer><button className="primary" onClick={() => print("فرم کاغذی پشتیبان گشت", paperFormBody())}><Printer size={15} />چاپ فرم</button></footer>
        </article>
        {GUIDES.map((guide) => (
          <article key={guide.id} className="report-card">
            <header><b><BookOpen size={16} /> {guide.title}</b><small>{guide.audience}</small></header>
            {guide.sections.map((s) => (
              <div key={s.heading}><b>{s.heading}</b><ul className="guide-list">{s.items.map((i) => <li key={i}>{i}</li>)}</ul></div>
            ))}
            <footer><button className="secondary" onClick={() => print(guide.title, guideBody(guide))}><Printer size={15} />چاپ</button></footer>
          </article>
        ))}
      </div>
    </section>
  );
}
