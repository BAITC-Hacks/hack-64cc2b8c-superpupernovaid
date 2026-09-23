export type Route = { view: 'dashboard' | 'new' | 'meeting' | 'tasks' | 'notifications'; demo: boolean; meetingId: string | null }
export function parseRoute(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#\/?/, '').split('?')
  const [view, id] = path.split('/')
  const valid = ['dashboard', 'new', 'meeting', 'tasks', 'notifications'].includes(view)
  const meetingId = view === 'meeting' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id ?? '') ? id : null
  return { view: valid ? view as Route['view'] : 'dashboard', meetingId, demo: !meetingId && view !== 'notifications' && new URLSearchParams(query).get('demo') === '1' }
}
export function routeHash(route: Route): string {
  return `#/${route.view}${route.view === 'meeting' && route.meetingId ? `/${route.meetingId}` : ''}${route.demo ? '?demo=1' : ''}`
}
