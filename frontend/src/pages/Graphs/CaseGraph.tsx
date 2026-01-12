import React, { useMemo, useState } from 'react'
import { Card, Input, Button, Space, Table, Tag, message, Switch } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { graphApi, SerialGraph } from '../../services/graphs'
import ReactECharts from 'echarts-for-react'

const CaseGraph: React.FC = () => {
  const [caseIdsInput, setCaseIdsInput] = useState('')
  const [graph, setGraph] = useState<SerialGraph | null>(null)
  const [showTables, setShowTables] = useState(false)

  const buildMutation = useMutation({
    mutationFn: (caseIds: number[]) => graphApi.buildSerial(caseIds),
    onSuccess: (data) => {
      setGraph(data)
      message.success('图谱生成完成')
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || '生成失败')
    },
  })

  const parseCaseIds = () =>
    caseIdsInput
      .split(',')
      .map((item) => parseInt(item.trim(), 10))
      .filter((id) => !Number.isNaN(id))

  const nodeColumns = [
    { title: '案件ID', dataIndex: 'id', key: 'id' },
    { title: '编号', dataIndex: 'case_number', key: 'case_number' },
    { title: '类型', dataIndex: 'case_type', key: 'case_type' },
    { title: '地点', dataIndex: 'location', key: 'location' },
    { title: '手法', dataIndex: 'modus_operandi', key: 'modus_operandi' },
  ]

  const edgeColumns = [
    { title: '来源', dataIndex: 'source', key: 'source' },
    { title: '目标', dataIndex: 'target', key: 'target' },
    {
      title: '原因',
      dataIndex: 'reasons',
      key: 'reasons',
      render: (value: string[]) => value.map((v) => <Tag key={v}>{v}</Tag>),
    },
    { title: '评分', dataIndex: 'score', key: 'score' },
  ]

  const categories = useMemo(() => {
    const map = new Map<string, number>()
    graph?.nodes?.forEach((node) => {
      const key = node.case_type || '未分类'
      if (!map.has(key)) {
        map.set(key, map.size)
      }
    })
    return Array.from(map.keys()).map((name) => ({ name }))
  }, [graph])

  const option = useMemo(() => {
    if (!graph) return {}
    const categoryIndex = new Map<string, number>()
    categories.forEach((cat, index) => categoryIndex.set(cat.name, index))

    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: any) => {
          if (params.dataType === 'edge') {
            const reasons = params.data?.reasons?.join(' / ') || ''
            return `关联评分: ${params.data?.score || 0}<br/>${reasons}`
          }
          return `${params.data?.case_number || ''}<br/>${params.data?.location || ''}`
        },
      },
      legend: [{ data: categories.map((c) => c.name) }],
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          label: { show: true },
          force: {
            repulsion: 160,
            edgeLength: 120,
          },
          data: graph.nodes.map((node) => ({
            id: String(node.id),
            name: node.case_number,
            value: node.case_type || '未分类',
            category: categoryIndex.get(node.case_type || '未分类') || 0,
            case_number: node.case_number,
            location: node.location,
          })),
          links: graph.edges.map((edge) => ({
            source: String(edge.source),
            target: String(edge.target),
            reasons: edge.reasons,
            score: edge.score,
            lineStyle: {
              width: 1 + edge.score * 2,
              opacity: 0.8,
            },
          })),
          categories,
        },
      ],
    }
  }, [graph, categories])

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card title="串案图谱引擎">
        <Space>
          <Input
            placeholder="输入案件ID，逗号分隔"
            value={caseIdsInput}
            onChange={(e) => setCaseIdsInput(e.target.value)}
            style={{ width: 360 }}
          />
          <Button
            type="primary"
            onClick={() => {
              const ids = parseCaseIds()
              if (!ids.length) {
                message.warning('请输入有效案件ID')
                return
              }
              buildMutation.mutate(ids)
            }}
            loading={buildMutation.isLoading}
          >
            生成图谱
          </Button>
        </Space>
        <Space style={{ marginLeft: 16 }}>
          <span>表格视图</span>
          <Switch checked={showTables} onChange={setShowTables} />
        </Space>
      </Card>

      {!showTables && (
        <Card title="图谱可视化">
          <ReactECharts option={option} style={{ height: 560 }} />
        </Card>
      )}

      {showTables && (
        <>
          <Card title="图谱节点">
            <Table
              rowKey="id"
              dataSource={graph?.nodes || []}
              columns={nodeColumns}
              pagination={{ pageSize: 8 }}
            />
          </Card>

          <Card title="图谱关系">
            <Table
              rowKey={(record) => `${record.source}-${record.target}`}
              dataSource={graph?.edges || []}
              columns={edgeColumns}
              pagination={{ pageSize: 8 }}
            />
          </Card>
        </>
      )}
    </Space>
  )
}

export default CaseGraph
