import type { Metadata } from "next";

import { FreeformComposer } from "@/components/freeform-composer";

export const metadata: Metadata = {
  title: "自由写作",
  description: "把碎片想法或 arXiv 论文链接整理成可以直接编辑发布的技术短帖。",
};

export default function ComposePage() {
  return (
    <main id="main-content" className="shell studio-page composer-page">
      <header className="studio-header">
        <p className="section-index">FREEFORM WRITING / NO DATABASE</p>
        <h1>从半个想法，写到可以发布。</h1>
        <p>
          不必先找到一个热点。把没说完的判断交进来，或者给出一篇 arXiv 论文；
          系统负责组织表达和核对资料边界，结果不会写入资讯库。
        </p>
      </header>
      <FreeformComposer />
    </main>
  );
}
