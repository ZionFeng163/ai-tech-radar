import { categoryLabels, openSourceLabels } from "@/lib/format";
import type { OpenSourceStatus, TechnicalCategory } from "@/lib/types";

interface FilterBarProps {
  action?: string;
  category?: string;
  importanceMin?: string;
  openSourceStatus?: string;
  query?: string;
  source?: string;
}

export function FilterBar({
  action = "/",
  category,
  importanceMin,
  openSourceStatus,
  query,
  source,
}: FilterBarProps) {
  return (
    <form className="filter-bar" action={action}>
      {query ? <input type="hidden" name="q" value={query} /> : null}
      <label>
        <span>技术分类</span>
        <select name="category" defaultValue={category ?? ""}>
          <option value="">全部分类</option>
          {(Object.entries(categoryLabels) as [TechnicalCategory, string][]).map(
            ([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ),
          )}
        </select>
      </label>
      <label>
        <span>来源</span>
        <select name="source" defaultValue={source ?? ""}>
          <option value="">全部来源</option>
          <option value="arxiv">arXiv</option>
          <option value="github-releases">GitHub Releases</option>
          <option value="hugging-face">Hugging Face</option>
        </select>
      </label>
      <label>
        <span>最低重要性</span>
        <select name="importance_min" defaultValue={importanceMin ?? ""}>
          <option value="">不限</option>
          <option value="8">8.0+</option>
          <option value="7">7.0+</option>
          <option value="5">5.0+</option>
        </select>
      </label>
      <label>
        <span>开放状态</span>
        <select name="open_source_status" defaultValue={openSourceStatus ?? ""}>
          <option value="">不限</option>
          {(Object.entries(openSourceLabels) as [OpenSourceStatus, string][]).map(
            ([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ),
          )}
        </select>
      </label>
      <button type="submit">应用筛选</button>
    </form>
  );
}
