// 外壳：顶栏（品牌+运行状态+时间窗+主题）+ tab 栏 + hash 路由。
import { useEffect, useState } from "react";
import { api } from "./api.js";
import Front from "./pages/front.jsx";
import Market from "./pages/market.jsx";
import NodePage from "./pages/node.jsx";
import Pictorial from "./pages/pictorial.jsx";
import Reading from "./pages/reading.jsx";
import Story from "./pages/story.jsx";
import Wrap from "./pages/wrap.jsx";

const TABS = [
  ["#/", "信息流"],
  ["#/reading", "阅读"],
  ["#/market", "市场快照"],
  ["#/pictorial", "画报"],
  ["#/wrap", "复盘"],
];
const WINDOWS = [["24H", 24], ["72H", 72], ["7D", 168], ["30D", 720]];

function useHash() {
  const [hash, setHash] = useState(location.hash || "#/");
  useEffect(() => {
    const fn = () => setHash(location.hash || "#/");
    addEventListener("hashchange", fn);
    return () => removeEventListener("hashchange", fn);
  }, []);
  return hash;
}

export default function App() {
  const hash = useHash();
  const [status, setStatus] = useState(null);
  const [windowH, setWindowH] = useState(72);
  const [theme, setTheme] = useState(
    document.documentElement.dataset.theme || "light",
  );

  useEffect(() => {
    Promise.all([api("/health"), api("/api/stats")])
      .then(([h, s]) => setStatus({ h, s }))
      .catch(() => {});
  }, []);

  function flipTheme() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    localStorage.setItem("na-theme", next);
    setTheme(next);
  }

  let page;
  const mStory = hash.match(/^#\/story\/(\d+)/);
  const mNode = hash.match(/^#\/node\/(\d+)/);
  if (mStory) page = <Story id={+mStory[1]} />;
  else if (mNode) page = <NodePage id={+mNode[1]} />;
  else if (hash.startsWith("#/reading")) page = <Reading />;
  else if (hash.startsWith("#/market")) page = <Market />;
  else if (hash.startsWith("#/pictorial")) page = <Pictorial />;
  else if (hash.startsWith("#/wrap")) page = <Wrap />;
  else page = <Front windowH={windowH} />;

  const tabOf = (h) =>
    mStory || mNode ? "#/" : TABS.find(([k]) => h === k || (k !== "#/" && h.startsWith(k)))?.[0] ?? "#/";

  return (
    <>
      <header className="topbar">
        <a className="brand" href="#/" style={{ textDecoration: "none" }}>
          NewsAssistant
        </a>
        {status && (
          <span className="statuschip">
            {status.h?.last_cycle != null && `cycle ${status.h.last_cycle} · `}
            {status.s.docs?.toLocaleString()} docs · {status.s.stories} stories
          </span>
        )}
        <span className="spacer" />
        <div className="segctl">
          {WINDOWS.map(([label, h]) => (
            <button key={h} className={windowH === h ? "on" : ""}
                    onClick={() => setWindowH(h)}>
              {label}
            </button>
          ))}
        </div>
        <button className="themebtn" onClick={flipTheme} title="主题切换">
          ◐
        </button>
      </header>
      <nav className="tabbar">
        {TABS.map(([href, label]) => (
          <a key={href} href={href} className={tabOf(hash) === href ? "on" : ""}>
            {label}
          </a>
        ))}
      </nav>
      {page}
    </>
  );
}
