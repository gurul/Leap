import Nav from './components/Nav.jsx'
import Hero from './components/Hero.jsx'
import CardRow from './components/CardRow.jsx'
import CallToAction from './components/CallToAction.jsx'

// Test bed for leap-input grab mode. Every component below is deliberately
// crude in one obvious way — a size, a colour, a spacing, an alignment — so
// there is always something real to point at and say "make this bigger".
export default function App() {
  return (
    <div className="page">
      <Nav />
      <Hero />
      <CardRow />
      <CallToAction />
    </div>
  )
}
