// SmartBanking on Azure Container Apps: one shared environment, one container
// app per entry in apps.json (the single list tests/test_cloud_infra.py
// checks), images pulled from the existing ACR by a user-assigned identity.
// Bicep compiles to an ARM template (Lecture 11, slides 12-14).
//   az deployment group create -g rg-smartbank --template-file deploy/azure/main.bicep \
//       --parameters acrName=<registry> imageTag=<git sha>

@description('Azure region for every resource.')
param location string = 'australiaeast'

@description('Name of the existing Azure Container Registry (deploy/azure/setup.sh creates it).')
param acrName string

@description('Image tag to deploy: the git commit the images were built from.')
param imageTag string

@description('Name of the Container Apps environment.')
param envName string = 'smartbank-env'

var apps = loadJsonContent('apps.json').apps
var features = ['accounts', 'loans', 'fraud', 'budgeting', 'transactions']
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

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

resource managedEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  properties: {
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

resource containerApps 'Microsoft.App/containerApps@2024-03-01' = [for app in apps: {
  name: app.name
  location: location
  dependsOn: [pullRole]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${pullIdentity.id}': {} }
  }
  properties: {
    managedEnvironmentId: managedEnv.id
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
    }
    template: {
      containers: [
        {
          name: app.name
          image: replace(replace(app.image, '{acr}', acrName), '{tag}', imageTag)
          command: app.?command
          env: [for item in items(app.env): {
            name: item.key
            value: replace(item.value, '{defaultDomain}', managedEnv.properties.defaultDomain)
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
