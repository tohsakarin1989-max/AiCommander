import React, { useState } from 'react'
import { Card, Input, Button, Space, List, Tag, message, Alert } from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { agentApi, AgentTask } from '../../services/agents'

const { TextArea } = Input

const AgentCenter: React.FC = () => {
  const [query, setQuery] = useState('')

  const {
    data,
    refetch,
    isFetching,
    isError,
    error,
  } = useQuery({
    queryKey: ['agent-tasks'],
    queryFn: agentApi.list,
  })

  const runMutation = useMutation({
    mutationFn: (q: string) => agentApi.run(q),
    onSuccess: () => {
      message.success('Agent 已完成任务')
      setQuery('')
      refetch()
    },
    onError: (error: any) => {
      message.error(error?.response?.data?.detail || '任务失败')
    },
  })

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card title="AI 侦查 Agent">
        <Space direction="vertical" style={{ width: '100%' }}>
          <TextArea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            rows={4}
            placeholder="描述目标，例如：找出近三个月同手法案件，并给出可追溯证据链。"
          />
          <Button
            type="primary"
            onClick={() => {
              if (!query.trim()) {
                message.warning('请输入任务目标')
                return
              }
              runMutation.mutate(query.trim())
            }}
            loading={runMutation.isLoading}
          >
            启动任务
          </Button>
        </Space>
      </Card>

      <Card title="任务记录" loading={isFetching}>
        {isError && (
          <Alert
            message="任务记录加载失败"
            description={error instanceof Error ? error.message : '请稍后重试'}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
          />
        )}
        <List
          dataSource={data || []}
          renderItem={(item: AgentTask) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    <span>任务 #{item.id}</span>
                    <Tag>{item.status}</Tag>
                  </Space>
                }
                description={
                  <div>
                    <div>目标：{item.query}</div>
                    <div>结果：{item.result?.result || '暂无结果'}</div>
                    <div>步骤：{(item.result?.steps || []).join(' / ')}</div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      </Card>
    </Space>
  )
}

export default AgentCenter
