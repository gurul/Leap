const CARDS = [
  { title: 'Grab', body: 'Cmd+C over an element copies its source location.' },
  { title: 'Speak', body: 'Thumbs-up holds the mic; the transcript is pasted.' },
  { title: 'Queue', body: 'Both land in one record the agent can act on.' },
]

export default function CardRow() {
  return (
    <section className="cards">
      {CARDS.map((c) => (
        <article className="card" key={c.title}>
          <h3 className="card-title">{c.title}</h3>
          <p className="card-body">{c.body}</p>
        </article>
      ))}
    </section>
  )
}
