// SmartBanking on Azure Container Apps: one shared environment, one container
// app per entry in apps.json (the single list tests/test_cloud_infra.py
// checks), images pulled from the existing ACR by a user-assigned identity.
// Bicep compiles to an ARM template (Lecture 11, slides 12-14).
//   az deployment group create -g rg-smartbank --template-file deploy/azure/main.bicep \
//       --parameters acrName=<registry> imageTag=<git sha>

@description('Azure region for every resource: the resource group\'s, which setup.sh creates in AZ_LOCATION.')
param location string = resourceGroup().location

@description('Name of the existing Azure Container Registry (deploy/azure/setup.sh creates it).')
param acrName string

@description('Image tag to deploy: the git commit the images were built from.')
param imageTag string

@description('Name of the Container Apps environment.')
param envName string = 'smartbank-env'

@description('AI-Mode (Gemini) in every backend. Off by default: the brief\'s cloud baseline. On is the bonus profile.')
param aiModeEnabled bool = false

@description('The shared MCP server as an app of its own, and the backends calling it. Off by default; on is bonus B2.')
param mcpEnabled bool = false

@description('The shared Multi-Agent Server as an app of its own, and the backends calling it. Off by default; on is bonus B4.')
param multiAgentEnabled bool = false

@secure()
@description('Gemini API key (the GEMINI_API_KEY repository secret). It reaches an app only as a Container Apps secret: the backends with aiModeEnabled, the Multi-Agent Server with multiAgentEnabled.')
param geminiApiKey string = ''

@secure()
@description('Bearer token between the backends and the Multi-Agent Server. New on every deployment, so nobody stores it.')
param multiAgentToken string = newGuid()

var apps = loadJsonContent('apps.json').apps
var features = ['accounts', 'loans', 'fraud', 'budgeting', 'transactions']
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

// apps.json keeps every backend's AI flags "false"; these switches override them.
var flags = {
  AI_MODE_ENABLED: aiModeEnabled ? 'true' : 'false'
  MCP_ENABLED: mcpEnabled ? 'true' : 'false'
  RAG_ENABLED: 'false'
  MULTI_AGENT_ENABLED: multiAgentEnabled ? 'true' : 'false'
}

// An app with a "switch" in apps.json (an AI server) is deployed only when that
// flag is on; every other app always is.
var deployWhen = union(flags, { ALWAYS: 'true' })

// The secrets each app reads, by the variable it reads them from: a backend
// gets the Gemini key with AI-Mode on and the token with Multi-Agent on; the
// Multi-Agent Server gets both, since its agents call Gemini.
var secretNames = {
  GEMINI_API_KEY: 'gemini-api-key'  // pragma: allowlist secret (the secret's name, not its value)
  MULTI_AGENT_API_TOKEN: 'multi-agent-token'  // pragma: allowlist secret (the secret's name, not its value)
}
var backendSecrets = concat(aiModeEnabled ? ['GEMINI_API_KEY'] : [], multiAgentEnabled ? ['MULTI_AGENT_API_TOKEN'] : [])
var serverSecrets = {
  MCP_ENABLED: []
  MULTI_AGENT_ENABLED: ['GEMINI_API_KEY', 'MULTI_AGENT_API_TOKEN']
}
var appSecrets = [for app in apps: app.role == 'backend' ? backendSecrets : (contains(app, 'switch') ? serverSecrets[app.switch] : [])]

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${envName}-logs'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// Explicitly a workload profiles environment on the free Consumption profile.
// Left unset, Azure now creates an "Express" environment, which refuses
// allowInsecure and has no internal service discovery, so the apps below could
// not call each other by name.
resource managedEnv 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: envName
  location: location
  properties: {
    environmentMode: 'WorkloadProfiles'
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// The apps pull from ACR as this identity: no registry password anywhere.
resource pullIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${envName}-acr-pull'
  location: location
}

resource pullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, pullIdentity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: pullIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [for (app, i) in apps: if (deployWhen[app.?switch ?? 'ALWAYS'] == 'true') {
  name: app.name
  location: location
  dependsOn: [pullRole]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${pullIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
    workloadProfileName: 'Consumption'
    configuration: {
      ingress: {
        // Only frontends are public. Internal apps also answer plain http,
        // which is how the backends call each other (http://<app-name>).
        external: app.external
        targetPort: app.targetPort
        transport: 'auto'
        allowInsecure: !app.external
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: pullIdentity.id
        }
      ]
      secrets: [for key in appSecrets[i]: {
        name: secretNames[key]
        value: key == 'GEMINI_API_KEY' ? geminiApiKey : multiAgentToken
      }]
    }
    template: {
      containers: [
        {
          name: app.name
          image: replace(replace(app.image, '{acr}', acrName), '{tag}', imageTag)
          command: app.?command
          // The AI flags come from the switches, and each secret this app gets
          // is read from its Container Apps secret, never written out as a value.
          env: [for item in items(union(app.env, toObject(appSecrets[i], key => key, key => ''))): contains(secretNames, item.key) ? {
            name: item.key
            secretRef: secretNames[item.key]
          } : {
            name: item.key
            value: flags[?item.key] ?? replace(item.value, '{defaultDomain}', managedEnv.properties.defaultDomain)
          }]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      scale: {
        minReplicas: app.minReplicas
        maxReplicas: app.maxReplicas
      }
    }
  }
}]

// Read by deploy/azure/checks.py (through deploy.sh's outputs.json).
output frontends object = toObject(features, f => f, f => 'https://${f}-frontend-service.${managedEnv.properties.defaultDomain}')
output homeUrl string = 'https://home.${managedEnv.properties.defaultDomain}'
