# Low-Level Design

## Status

This document describes the proposed target design for separating MCP wiring,
application orchestration, LinkedIn UI automation, browser mechanics, and
capability-owned code. It is an implementation design, not a description of
the current package layout.

In the diagrams:

- `*--` means lifecycle ownership;
- `o--` means an injected dependency;
- `-->` means a call or other use; and
- `..|>` means that a concrete class implements a protocol.

## Core classes

```mermaid
classDiagram
direction TB

class FastMCPServer {
    +start()
    +callTool(name, arguments)
    +close()
}

class ToolDefinition {
    <<MCPAdapter>>
    +register(server, container)
    +handle(arguments) ToolOutput
}

class AppContainer {
    +settings Settings
    +start()
    +quiesce()
    +close()
}

class AccountProcessLock {
    +acquire()
    +release()
}

class ClientSessionRegistry {
    +resolve(session) ClientId
}

class CapabilityWorker {
    -queue Queue~WorkItem~
    -scheduler FairClientScheduler
    +start()
    +submit(capability, request) ToolOutput
    +quiesce()
    +close()
}

class FairClientScheduler {
    +enqueue(workItem)
    +next() WorkItem
    +cancel(key)
}

class WorkItem {
    +clientId
    +capabilityName
    +request
    +future
    +paginationLease
    +cancelRequested
}

class CapabilityExecutor {
    -operations
    +searchJobs(request)
    +getJob(request)
    +searchPeople(request)
    +executeOtherCapability(request)
    +close()
}

class CapabilityOperation {
    <<Protocol>>
    +execute(request) ToolOutput
}

class ReadOperation {
    +execute(request) ReadOutput
}

class WriteOperation {
    +execute(request) ActionOutput
}

class PaginationManager {
    +acquire(request) PaginationLease
    +advance(lease, results) PaginationMetadata
    +abort(lease)
    +close()
}

class PaginationLease {
    +accountId
    +clientId
    +capabilityName
    +seenKeys
    +binding
}

class ActionExecutor {
    +execute(request, inspect, commandFactory, perform) ActionOutput
}

class ReadPage {
    <<Protocol>>
    +collect(request, resultLimit) PageCapture
}

class ActionPage {
    <<Protocol>>
    +inspect(request) ActionInspection
    +perform(command) ActionPageResult
}

class LinkedInUISession {
    -paused bool
    -pauseReason str
    +start()
    +page() AsyncContextManager~Page~
    +navigate(page, url)
    +navigateVia(page, locator)
    +click(page, locator)
    +assertSafe(page)
    +status() UISessionStatus
    +close()
}

class AuthenticationCoordinator {
    -state AuthenticationState
    -backgroundTask
    +start()
    +ensureReady()
    +markAuthenticated()
    +requestReauthentication(reason)
    +markAttentionRequired(error)
    +close()
}

class LinkedInNavigator {
    +navigate(page, url)
    +navigateVia(page, locator)
    +click(page, locator)
}

class NavigationPacer {
    -limiter
    +wait()
    +close()
}

class LinkedInSafetyGuard {
    +check(page)
}

class CollectionHelpers {
    <<Module>>
    +waitForInitialState()
    +waitForChange()
    +waitForInteraction()
    +visibleSignature()
}

class BrowserRuntime {
    -playwright
    -browserContext
    -operationLock
    +startSetup()
    +ensureProfile()
    +page() AsyncContextManager~Page~
    +stop()
    +close()
}

class BrowserRuntimeBootstrap {
    +start()
    +ensureReady()
    +close()
}

class BrowserProfileManager {
    +inspect() ProfileState
    +ensureCreated()
    +reset()
}

class Playwright {
    <<ExternalSDK>>
    +start()
    +stop()
}

class BrowserContext {
    +newPage() Page
    +close()
}

class Page {
    <<PlaywrightType>>
    +goto(url)
    +locator(selector)
    +getByRole(role, name)
    +close()
}

class LocalAssetStore {
    +resolve(reference) Path
}

FastMCPServer *-- ToolDefinition : exposes
FastMCPServer o-- AppContainer : lifecycle

AppContainer *-- AccountProcessLock
AppContainer *-- ClientSessionRegistry
AppContainer *-- CapabilityWorker
AppContainer *-- CapabilityExecutor
AppContainer *-- PaginationManager
AppContainer *-- ActionExecutor
AppContainer *-- LinkedInUISession
AppContainer *-- BrowserRuntime
AppContainer *-- LocalAssetStore

ToolDefinition --> CapabilityWorker : submits typed request
ToolDefinition --> ClientSessionRegistry : resolves client

CapabilityWorker *-- FairClientScheduler
CapabilityWorker *-- WorkItem
CapabilityWorker --> CapabilityExecutor : invokes one operation

CapabilityExecutor o-- CapabilityOperation : delegates
CapabilityOperation <|.. ReadOperation
CapabilityOperation <|.. WriteOperation

ReadOperation o-- ReadPage
ReadOperation o-- PaginationManager
PaginationManager *-- PaginationLease

WriteOperation o-- ActionPage
WriteOperation o-- ActionExecutor
WriteOperation o-- LocalAssetStore : when required

ReadPage --> LinkedInUISession
ActionPage --> LinkedInUISession
ReadPage --> CollectionHelpers
ActionPage --> CollectionHelpers

LinkedInUISession o-- BrowserRuntime
LinkedInUISession o-- AuthenticationCoordinator
LinkedInUISession *-- LinkedInNavigator

LinkedInNavigator *-- NavigationPacer
LinkedInNavigator *-- LinkedInSafetyGuard

BrowserRuntime *-- BrowserRuntimeBootstrap
BrowserRuntime *-- BrowserProfileManager
BrowserRuntime --> Playwright
BrowserRuntime --> BrowserContext
BrowserContext --> Page : creates
LinkedInUISession --> Page : operation-scoped use
```

## Capability classes

Every capability follows the same vertical-slice pattern. Job search represents
a read capability, while invitation send represents an account-changing
capability.

```mermaid
classDiagram
direction LR

class ToolInput {
    <<PydanticModel>>
    +contextId
    +requestId
}

class ToolOutput {
    <<PydanticModel>>
    +contextId
    +requestId
    +sources
}

class SourceReference {
    +sourceId
    +sourceType
    +sourceUrl
    +capturedAt
}

class JobSearchTool {
    +register(mcp, container)
}

class JobSearchInput
class JobSearchOutput

class JobSearchCapture {
    +jobs
    +coverage
    +capturedText
    +sourceUrl
    +capturedAt
}

class SearchJobsOperation {
    -page JobSearchPage
    -pagination PaginationManager
    +execute(request) JobSearchOutput
}

class JobSearchPage {
    -ui LinkedInUISession
    -maxPages int
    +collect(request, resultLimit) JobSearchCapture
    -applyFilters(page, filters)
    -extractVisibleJobs(page)
    -reconcileInventory(page, jobs)
}

class JobSearchEvidence {
    <<Module>>
    +build(capture, selectedJobs) SourceReference
}

class InvitationSendTool {
    +register(mcp, container)
}

class InvitationSendInput

class SendInvitationOperation {
    -page SendInvitationPage
    -actions ActionExecutor
    +execute(request) ActionOutput
}

class SendInvitationPage {
    -ui LinkedInUISession
    +inspect(request) ActionInspection
    +perform(command) ActionPageResult
}

class ActionInspection {
    +target
    +currentState
    +sourceUrl
    +capturedText
    +capturedAt
}

class ActionCommand {
    +actionType
    +target
    +payload
}

class ActionPageResult {
    +outcome
    +performed
    +finalState
    +sourceUrl
    +capturedText
    +capturedAt
}

class ActionOutput {
    +contextId
    +requestId
    +result
    +sources
}

ToolInput <|-- JobSearchInput
ToolOutput <|-- JobSearchOutput
ToolOutput <|-- ActionOutput
ToolInput <|-- InvitationSendInput

JobSearchTool --> JobSearchInput : constructs
JobSearchTool --> SearchJobsOperation : queued invocation
SearchJobsOperation o-- JobSearchPage
SearchJobsOperation --> JobSearchEvidence
SearchJobsOperation --> JobSearchOutput
JobSearchPage --> JobSearchCapture
JobSearchEvidence --> SourceReference
JobSearchOutput *-- SourceReference

InvitationSendTool --> InvitationSendInput : constructs
InvitationSendTool --> SendInvitationOperation : queued invocation
SendInvitationOperation o-- SendInvitationPage
SendInvitationOperation --> ActionCommand : constructs after inspection
SendInvitationPage --> ActionInspection
SendInvitationPage --> ActionPageResult
SendInvitationOperation --> ActionOutput
ActionOutput *-- SourceReference
```

## Read interaction

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Tool as JobSearchTool
    participant Worker as CapabilityWorker
    participant Executor as CapabilityExecutor
    participant Operation as SearchJobsOperation
    participant PageObject as JobSearchPage
    participant UI as LinkedInUISession
    participant Browser as BrowserRuntime
    participant PW as Playwright Page

    Client->>Tool: linkedin.jobs.search(arguments)
    Tool->>Tool: Validate and create JobSearchInput
    Tool->>Worker: searchJobs(request)
    Worker->>Worker: Enqueue WorkItem
    Worker->>Executor: searchJobs(request)
    Executor->>Operation: execute(request)
    Operation->>Operation: Acquire PaginationLease
    Operation->>PageObject: collect(request, resultLimit)

    PageObject->>UI: page()
    UI->>UI: Ensure authentication is ready
    UI->>Browser: page()
    Browser->>PW: Create operation-scoped page

    PageObject->>UI: navigate(page, searchUrl)
    UI->>UI: Pace, validate, and check safety
    UI->>PW: goto(searchUrl)

    PageObject->>PW: Apply visible filters
    PageObject->>PW: Read visible result cards
    PageObject->>PageObject: Reconcile inventory
    PageObject-->>Operation: JobSearchCapture

    Operation->>Operation: Select cursor page
    Operation->>Operation: Build coverage and evidence
    Operation->>Operation: Advance PaginationLease
    Operation-->>Executor: JobSearchOutput
    Executor-->>Worker: JobSearchOutput
    Worker-->>Tool: Resolve WorkItem future
    Tool-->>Client: Typed MCP response
```

## Write interaction

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Tool as InvitationSendTool
    participant Worker as CapabilityWorker
    participant Operation as SendInvitationOperation
    participant Actions as ActionExecutor
    participant PageObject as SendInvitationPage
    participant UI as LinkedInUISession
    participant PW as Playwright Page

    Client->>Tool: linkedin.invitations.send(arguments)
    Tool->>Worker: Submit InvitationSendInput
    Worker->>Operation: execute(request)
    Operation->>Actions: execute(inspect, commandFactory, perform)

    Actions->>PageObject: inspect(request)
    PageObject->>UI: Open safe operation page
    UI->>PW: Navigate using visible UI
    PageObject->>PW: Read target and current state
    PageObject-->>Actions: ActionInspection

    Actions->>Actions: Build immutable ActionCommand
    Actions->>PageObject: perform(command)
    PageObject->>PW: Invoke final LinkedIn control once
    PageObject->>PW: Verify visible postcondition
    PageObject-->>Actions: ActionPageResult

    alt Outcome visibly verified
        Actions-->>Operation: VERIFIED ActionOutput and evidence
    else Failure before final control
        Actions-->>Operation: FAILED ActionOutput
    else Final control may have run before interruption
        Actions-->>Operation: UNCERTAIN ActionOutput
        Note over Actions,Operation: Never retry automatically
    end

    Operation-->>Worker: ActionOutput
    Worker-->>Tool: Resolve WorkItem future
    Tool-->>Client: Typed MCP response
```

## Authentication states

```mermaid
stateDiagram-v2
    [*] --> UNVERIFIED: saved profile exists
    [*] --> LOGIN_REQUIRED: no saved profile

    UNVERIFIED --> VALIDATING: automatic startup
    LOGIN_REQUIRED --> LOGIN_IN_PROGRESS: start interactive login
    LOGIN_IN_PROGRESS --> VALIDATING: login browser closes successfully
    VALIDATING --> AUTHENTICATED: visible session validation succeeds
    VALIDATING --> LOGIN_IN_PROGRESS: saved session requires login

    AUTHENTICATED --> LOGIN_REQUIRED: session expires
    LOGIN_REQUIRED --> LOGIN_IN_PROGRESS: automatic reauthentication

    UNVERIFIED --> ATTENTION_REQUIRED: setup or validation failure
    LOGIN_IN_PROGRESS --> ATTENTION_REQUIRED: login failure
    VALIDATING --> ATTENTION_REQUIRED: checkpoint or restriction
    AUTHENTICATED --> ATTENTION_REQUIRED: checkpoint or restriction

    ATTENTION_REQUIRED --> LOGIN_REQUIRED: operator requests reauthentication
```

## Dependency direction

```text
MCP tool
    -> capability worker
        -> capability executor
            -> capability operation
                -> capability page object
                    -> LinkedIn UI session
                        -> browser runtime
                            -> Playwright
```

Capability page objects never own a browser or retain a Playwright `Page`.
They receive `LinkedInUISession`, use an operation-scoped page, and return typed
captures. `LinkedInUISession` owns LinkedIn-wide automation behavior, while
`BrowserRuntime` remains a low-level Playwright resource manager.
