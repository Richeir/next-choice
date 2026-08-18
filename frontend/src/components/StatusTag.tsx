/** 分析状态标签：已分析（绿）/ 待分析（灰） */
export default function StatusTag({ analyzed }: { analyzed: boolean }) {
  return <span className={`tag ${analyzed ? 'analyzed' : 'pending'}`}>{analyzed ? '已分析' : '待分析'}</span>;
}
